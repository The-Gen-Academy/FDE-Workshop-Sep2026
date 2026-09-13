"""Run customer turns locally or through Vertex AI Agent Engine."""

import asyncio
import os
import uuid

from claims_core.config import evidence_bucket
from claims_core.evidence import load_photo
from google.genai import types
from google.genai.errors import ClientError

MAX_ATTEMPTS = 3
INITIAL_BACKOFF_SECONDS = 2
APP_NAME = "insurance_claim_agent"
LOCAL_SESSION_INSTANCE = uuid.uuid4().hex

_remote_agent = None
_local_runner = None


class AgentTurnError(RuntimeError):
    """The agent reported a failure event instead of completing the turn."""


def selected_backend() -> str:
    backend = os.environ.get("AGENT_BACKEND", "local").strip().lower()
    if backend not in {"local", "vertex"}:
        raise ValueError("AGENT_BACKEND must be local or vertex.")
    return backend


def _get_remote_agent():
    global _remote_agent
    if _remote_agent is None:
        agent_engine_id = os.environ.get("AGENT_ENGINE_ID")
        if not agent_engine_id:
            raise RuntimeError("Set AGENT_ENGINE_ID when AGENT_BACKEND=vertex.")
        if os.environ.get("CLAIMS_STORE", "local").lower() != "firestore" or not evidence_bucket():
            raise RuntimeError(
                "Vertex chat requires CLAIMS_STORE=firestore and CLAIMS_EVIDENCE_BUCKET "
                "pointing to the same database and evidence bucket as the deployed agent."
            )
        missing = [
            name
            for name in ("GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION")
            if not os.environ.get(name)
        ]
        if missing:
            raise RuntimeError(f"Vertex chat requires {', '.join(missing)}.")
        import vertexai
        from vertexai import agent_engines

        vertexai.init(
            project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=os.environ.get("GOOGLE_CLOUD_LOCATION"),
        )
        _remote_agent = agent_engines.get(agent_engine_id)
    return _remote_agent


def _get_local_runner():
    global _local_runner
    if _local_runner is None:
        try:
            from google.adk.runners import Runner
            from google.adk.sessions import InMemorySessionService
            from insurance_claim_agent.agent import root_agent
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Local chat requires the agent extra: "
                "uv sync --package claims-local-apps --extra local-agent"
            ) from exc
        _local_runner = Runner(
            app_name=APP_NAME,
            agent=root_agent,
            session_service=InMemorySessionService(),
        )
    return _local_runner


def new_user_id() -> str:
    return uuid.uuid4().hex


async def start_session(user_id: str) -> str:
    if selected_backend() == "vertex":
        session = await _get_remote_agent().async_create_session(user_id=user_id)
        return session["id"]
    session = await _get_local_runner().session_service.create_session(
        app_name=APP_NAME, user_id=user_id
    )
    return session.id


def _message_content(text: str, images: list[tuple[str, str]], backend: str) -> types.Content:
    parts = [types.Part(text=text)] if text else []
    vertex_model = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").upper() == "TRUE"
    for ref, mime_type in images:
        if ref.startswith("gs://") and (backend == "vertex" or vertex_model):
            parts.append(types.Part.from_uri(file_uri=ref, mime_type=mime_type))
        else:
            parts.append(types.Part.from_bytes(data=load_photo(ref), mime_type=mime_type))
    return types.Content(role="user", parts=parts)


async def send_turn(
    user_id: str, session_id: str, text: str, images: list[tuple[str, str]]
) -> dict:
    """Send text and saved photo references; retry transient model throttling."""
    backend = selected_backend()
    content = _message_content(text, images, backend)
    backoff = INITIAL_BACKOFF_SECONDS
    for attempt in range(MAX_ATTEMPTS):
        try:
            return await _run_once(backend, user_id, session_id, content)
        except ClientError as exc:
            if exc.code != 429:
                raise
            if attempt == MAX_ATTEMPTS - 1:
                return _empty_result(rate_limited=True)
            await asyncio.sleep(backoff)
            backoff *= 2
    return _empty_result(rate_limited=True)


def _empty_result(*, rate_limited: bool = False) -> dict:
    return {
        "reply_text": "",
        "claim_id": None,
        "needs_more_photos": None,
        "outcome": None,
        "rate_limited": rate_limited,
    }


async def _events(backend: str, user_id: str, session_id: str, content: types.Content):
    if backend == "vertex":
        message = content.model_dump(mode="json", exclude_none=True)
        async for event in _get_remote_agent().async_stream_query(
            message=message, user_id=user_id, session_id=session_id
        ):
            yield event
    else:
        async for event in _get_local_runner().run_async(
            user_id=user_id, session_id=session_id, new_message=content
        ):
            yield event.model_dump(mode="json", exclude_none=True)


async def _run_once(backend: str, user_id: str, session_id: str, content: types.Content) -> dict:
    result = _empty_result()
    reply_chunks = []
    async for event in _events(backend, user_id, session_id, content):
        if event.get("error_code") or event.get("error_message"):
            raise AgentTurnError(
                f"{event.get('error_code') or 'AGENT_ERROR'}: "
                f"{event.get('error_message') or 'the agent returned an error event'}"
            )
        if event.get("partial"):
            continue
        parts = (event.get("content") or {}).get("parts") or []
        if event.get("author") in {"intake_agent", "reply_agent"}:
            reply_chunks.extend(
                part["text"] for part in parts if part.get("text") and not part.get("thought")
            )
        for part in parts:
            response = part.get("function_response") or {}
            payload = response.get("response") or {}
            if response.get("name") == "start_claim_intake":
                result["claim_id"] = payload.get("claim_id", result["claim_id"])
            elif response.get("name") == "record_damage_evidence" and payload.get("error"):
                result["needs_more_photos"] = payload["error"]
            elif response.get("name") == "package_for_adjuster" and payload:
                result["outcome"] = payload
    result["reply_text"] = "\n\n".join(reply_chunks)
    return result
