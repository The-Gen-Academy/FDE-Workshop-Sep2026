"""Customer sessions, chat history, and image uploads."""

from claims_core.evidence import save_customer_photo
from claims_core.storage import get_store
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from . import runner_service
from .schemas import MessageResponse, StartSessionRequest, StartSessionResponse

router = APIRouter(prefix="/api")

MAX_IMAGE_BYTES = 10 * 1024 * 1024

_SESSION_COLLECTION = "client_sessions"


def _load_session(session_id: str) -> dict | None:
    snapshot = get_store().collection(_SESSION_COLLECTION).document(session_id).get()
    if not snapshot.exists:
        return None
    state = snapshot.to_dict()
    backend = runner_service.selected_backend()
    if state.get("backend", "vertex") != backend:
        return None
    # Local ADK sessions expire when this process restarts.
    if backend == "local" and state.get("local_instance") != runner_service.LOCAL_SESSION_INSTANCE:
        return None
    return state


def _save_session(session_id: str, state: dict) -> None:
    get_store().collection(_SESSION_COLLECTION).document(session_id).set(state)


async def _send_turn(user_id: str, session_id: str, text: str, images: list) -> dict:
    # Surface agent failures (e.g. an unavailable model) instead of an empty reply.
    try:
        return await runner_service.send_turn(user_id, session_id, text, images)
    except runner_service.AgentTurnError as exc:
        raise HTTPException(status_code=502, detail=f"claims agent failed: {exc}") from exc


@router.post("/session", response_model=StartSessionResponse)
async def create_session(body: StartSessionRequest):
    user_id = runner_service.new_user_id()
    session_id = await runner_service.start_session(user_id)
    state = {
        "user_id": user_id,
        "policy_number": body.policy_number,
        "claim_id": None,
        "transcript": [],
        "outcome": None,
        "photo_count": 0,
        "backend": runner_service.selected_backend(),
        "local_instance": runner_service.LOCAL_SESSION_INSTANCE,
    }
    _save_session(session_id, state)

    # Prompt the greeting without adding synthetic customer text to the history.
    opening = "Hi, I'd like to file a claim."
    if body.policy_number.strip():
        opening += f" My policy number is {body.policy_number.strip()}."
    result = await _send_turn(user_id, session_id, opening, [])
    if not result["rate_limited"] and result["reply_text"]:
        state["transcript"].append({"role": "assistant", "text": result["reply_text"]})
        _save_session(session_id, state)

    return {"session_id": session_id, "policy_number": body.policy_number}


@router.get("/session/{session_id}/history")
def get_history(session_id: str):
    state = _load_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="session not found")
    return {k: v for k, v in state.items() if k not in {"user_id", "local_instance", "backend"}}


@router.post("/session/{session_id}/message", response_model=MessageResponse)
async def post_message(
    session_id: str, text: str = Form(""), images: list[UploadFile] = File(default=[])
):
    state = _load_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="session not found")

    image_refs = []
    for image in images:
        data = await image.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=413, detail=f"{image.filename} exceeds the 10MB per-photo limit"
            )
        mime_type = image.content_type or "image/jpeg"
        try:
            ref = save_customer_photo(session_id, state["photo_count"], data, mime_type)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        state["photo_count"] += 1
        image_refs.append((ref, mime_type))

    state["transcript"].append({"role": "customer", "text": text, "photo_count": len(image_refs)})
    _save_session(session_id, state)
    result = await _send_turn(state["user_id"], session_id, text, image_refs)

    if result["rate_limited"]:
        return result

    if result["claim_id"]:
        state["claim_id"] = result["claim_id"]
    if result["outcome"]:
        state["outcome"] = result["outcome"]
    state["transcript"].append({"role": "assistant", "text": result["reply_text"]})
    _save_session(session_id, state)
    return result
