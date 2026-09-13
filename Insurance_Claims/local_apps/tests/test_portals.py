from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock

import pytest
from adjuster_portal.app import app as adjuster_app
from claims_core import decisions, policies
from claims_core.evidence import load_photo
from client_portal import runner_service
from client_portal.app import app as client_app
from fastapi.testclient import TestClient


def pending_claim(store, claim_id="CLM-1"):
    store.collection("escalations").document(claim_id).set(
        {
            "claim_id": claim_id,
            "status": "pending_review",
            "policy_number": "POL-1",
            "policy": {"policyholder_name": "Alex", "coverage": {"limits": 5000}},
            "priority_result": {"priority": "medium"},
            "recommendation": {"recommended_action": "approve"},
            "queued_at": "2026-09-01T00:00:00+00:00",
        }
    )


def test_adjuster_queue_decision_and_history(local_store):
    pending_claim(local_store)
    client = TestClient(adjuster_app)
    assert client.get("/").status_code == 200
    assert (
        client.get("/api/queue", params={"q": "Alex", "priority": "medium"}).json()[0]["claim_id"]
        == "CLM-1"
    )
    assert client.get("/api/queue", params={"priority": "high"}).json() == []
    assert (
        client.post(
            "/api/claims/CLM-1/decision", json={"action": "approve", "amount": 6000}
        ).status_code
        == 400
    )
    assert local_store.collection("claims_log").list_all() == {}

    response = client.post(
        "/api/claims/CLM-1/decision", json={"action": "deny", "reason": "Excluded use"}
    )
    assert response.status_code == 200
    assert response.json()["override_reason"] == "Excluded use"
    assert client.get("/api/queue").json() == []
    assert client.get("/api/claims/CLM-1").json()["is_resolved"] is True
    assert len(client.get("/api/history", params={"override_only": True}).json()) == 1
    assert client.post("/api/claims/CLM-1/decision", json={"action": "deny"}).status_code == 409
    assert client.get("/api/claims/missing").status_code == 404
    assert response.headers["cache-control"] == "no-store"


def test_two_adjusters_cannot_resolve_the_same_claim(local_store):
    pending_claim(local_store)

    def decide(action):
        try:
            return decisions.submit_decision("CLM-1", action, 1000, "Reviewed")
        except decisions.ClaimAlreadyResolved:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(decide, ["approve", "deny"]))
    assert sum(outcome is not None for outcome in outcomes) == 1
    winner = next(outcome for outcome in outcomes if outcome is not None)
    assert local_store.collection("claims_log").document("CLM-1").get().to_dict() == winner
    claim = local_store.collection("escalations").document("CLM-1").get().to_dict()
    assert claim["resolved_at"] == winner["logged_at"]


@pytest.fixture
def policy_input():
    return dict(
        policyholder_name="  Alex  ",
        vin="test-vin",
        listed_drivers=[" Alex "],
        collision=True,
        comprehensive=True,
        deductible=500,
        limits=10000,
        effective_date="2026-01-01",
        expiration_date="2027-01-01",
        exclusions=["racing"],
    )


def test_policy_create_and_duplicate_protection(local_store, policy_input, monkeypatch):
    fixed_id = type("FixedID", (), {"hex": "abcdef01"})()
    monkeypatch.setattr(policies.uuid, "uuid4", lambda: fixed_id)
    client = TestClient(adjuster_app)
    response = client.post("/api/policies", json=policy_input)
    assert response.status_code == 200
    created = response.json()
    assert created["policyholder_name"] == "Alex"
    assert created["vin"] == "TEST-VIN"
    assert client.post("/api/policies", json=policy_input).status_code == 409
    assert client.get("/api/policies").json() == [created]


@pytest.mark.parametrize(
    "changes",
    [
        {"limits": float("inf")},
        {"deductible": float("nan")},
        {"effective_date": "not-a-date"},
        {"expiration_date": "2025-01-01"},
        {"exclusions": ["unknown"]},
    ],
)
def test_invalid_policy_never_writes(local_store, policy_input, changes):
    with pytest.raises(policies.PolicyValidationError):
        policies.create_policy(**(policy_input | changes))
    assert local_store.collection("policies").list_all() == {}


def test_customer_chat_upload_and_local_session_expiry(local_store, monkeypatch):
    start = AsyncMock(return_value="session-1")
    turn = AsyncMock(
        side_effect=[
            runner_service._empty_result() | {"reply_text": "How can I help?"},
            runner_service._empty_result() | {"reply_text": "Received.", "claim_id": "CLM-1"},
        ]
    )
    monkeypatch.setattr(runner_service, "start_session", start)
    monkeypatch.setattr(runner_service, "send_turn", turn)
    client = TestClient(client_app)
    assert client.get("/").status_code == 200
    response = client.post("/api/session", json={"policy_number": "POL-1"})
    assert response.json()["session_id"] == "session-1"
    response = client.post(
        "/api/session/session-1/message",
        data={"text": "Damage"},
        files={"images": ("damage.jpg", b"photo", "image/jpeg")},
    )
    assert response.status_code == 200
    assert response.json()["claim_id"] == "CLM-1"
    photo_ref = turn.await_args.args[3][0][0]
    assert load_photo(photo_ref) == b"photo"
    history = client.get("/api/session/session-1/history").json()
    assert [entry["role"] for entry in history["transcript"]] == [
        "assistant",
        "customer",
        "assistant",
    ]
    assert "user_id" not in history and "local_instance" not in history
    monkeypatch.setattr(runner_service, "LOCAL_SESSION_INSTANCE", "restarted")
    assert client.get("/api/session/session-1/history").status_code == 404


def test_vertex_history_survives_local_restart(local_store, monkeypatch):
    monkeypatch.setenv("AGENT_BACKEND", "vertex")
    local_store.collection("client_sessions").document("session-1").set(
        {
            "backend": "vertex",
            "user_id": "u",
            "local_instance": "previous-process",
            "transcript": [],
        }
    )
    assert TestClient(client_app).get("/api/session/session-1/history").status_code == 200
    monkeypatch.setenv("AGENT_BACKEND", "local")
    assert TestClient(client_app).get("/api/session/session-1/history").status_code == 404


def test_missing_or_invalid_historical_photos_return_404(local_store, tmp_path):
    pending_claim(local_store)
    local_store.collection("escalations").document("CLM-1").set(
        {
            "evidence": {
                "photo_refs": [str(tmp_path / "photos/missing.jpg"), "/outside/data/photo.jpg"]
            }
        },
        merge=True,
    )
    client = TestClient(adjuster_app)
    assert client.get("/api/claims/CLM-1/photos/0").status_code == 404
    assert client.get("/api/claims/CLM-1/photos/1").status_code == 404
    assert client.get("/api/claims/CLM-1/photos/2").status_code == 404
