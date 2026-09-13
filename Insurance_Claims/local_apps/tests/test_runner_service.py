import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from claims_core.evidence import save_customer_photo
from client_portal import runner_service as runner
from google.genai import types
from google.genai.errors import ClientError

EVENTS = [
    {
        "author": "intake_agent",
        "content": {"parts": [{"text": "Private reasoning", "thought": True}]},
    },
    {"author": "intake_agent", "partial": True, "content": {"parts": [{"text": "partial"}]}},
    {"author": "assessment_agent", "content": {"parts": [{"text": "internal assessment"}]}},
    {"author": "intake_agent", "content": {"parts": [{"text": "Hello"}]}},
    {
        "author": "intake_agent",
        "content": {
            "parts": [
                {
                    "function_response": {
                        "name": "start_claim_intake",
                        "response": {"claim_id": "CLM-1"},
                    }
                }
            ]
        },
    },
    {
        "author": "intake_agent",
        "content": {
            "parts": [
                {
                    "function_response": {
                        "name": "record_damage_evidence",
                        "response": {"error": "Please add a wide shot."},
                    }
                }
            ]
        },
    },
    {
        "author": "escalation_agent",
        "content": {
            "parts": [
                {
                    "function_response": {
                        "name": "package_for_adjuster",
                        "response": {"status": "pending_review"},
                    }
                }
            ]
        },
    },
    {"author": "reply_agent", "content": {"parts": [{"text": "An adjuster will review it."}]}},
]


@pytest.mark.parametrize("backend", ["local", "vertex"])
def test_transports_preserve_chat_and_structured_events(local_store, monkeypatch, backend):
    monkeypatch.setenv("AGENT_BACKEND", backend)
    calls = []

    async def remote_stream(**kwargs):
        calls.append(kwargs)
        for event in EVENTS:
            yield event

    async def local_stream(**kwargs):
        calls.append(kwargs)
        for event in EVENTS:
            yield SimpleNamespace(model_dump=lambda event=event, **_: event)

    sessions = SimpleNamespace(
        create_session=AsyncMock(return_value=SimpleNamespace(id="session-1"))
    )
    local = SimpleNamespace(session_service=sessions, run_async=local_stream)
    remote = SimpleNamespace(
        async_create_session=AsyncMock(return_value={"id": "session-1"}),
        async_stream_query=remote_stream,
    )
    monkeypatch.setattr(runner, "_get_local_runner", lambda: local)
    monkeypatch.setattr(runner, "_get_remote_agent", lambda: remote)
    photo = save_customer_photo("session-1", 0, b"photo-bytes", "image/jpeg")

    assert asyncio.run(runner.start_session("customer")) == "session-1"
    result = asyncio.run(
        runner.send_turn("customer", "session-1", "Claim details", [(photo, "image/jpeg")])
    )

    assert result == {
        "reply_text": "Hello\n\nAn adjuster will review it.",
        "claim_id": "CLM-1",
        "needs_more_photos": "Please add a wide shot.",
        "outcome": {"status": "pending_review"},
        "rate_limited": False,
    }
    if backend == "local":
        assert isinstance(calls[0]["new_message"], types.Content)
        assert calls[0]["new_message"].parts[1].inline_data.data == b"photo-bytes"
        sessions.create_session.assert_awaited_once_with(
            app_name=runner.APP_NAME, user_id="customer"
        )
    else:
        assert (
            calls[0]["message"]["parts"][1]["inline_data"]["data"]
            == base64.b64encode(b"photo-bytes").decode()
        )
        remote.async_create_session.assert_awaited_once_with(user_id="customer")


def test_vertex_passes_gcs_photo_uri_without_downloading(monkeypatch):
    monkeypatch.setattr(runner, "load_photo", lambda _: pytest.fail("GCS photo was downloaded"))
    content = runner._message_content("", [("gs://evidence/photos/1.jpg", "image/jpeg")], "vertex")
    assert content.parts[0].file_data.file_uri == "gs://evidence/photos/1.jpg"


def test_local_api_key_mode_sends_gcs_photo_bytes(monkeypatch):
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")
    monkeypatch.setattr(runner, "load_photo", lambda _: b"photo")
    content = runner._message_content("", [("gs://evidence/photos/1.jpg", "image/jpeg")], "local")
    assert content.parts[0].inline_data.data == b"photo"


def test_exhausted_quota_has_a_specific_result(monkeypatch):
    monkeypatch.setenv("AGENT_BACKEND", "local")
    run = AsyncMock(side_effect=ClientError(429, {"error": {"message": "quota exhausted"}}))
    sleep = AsyncMock()
    monkeypatch.setattr(runner, "_run_once", run)
    monkeypatch.setattr(runner.asyncio, "sleep", sleep)
    assert asyncio.run(runner.send_turn("u", "s", "hello", []))["rate_limited"] is True
    assert run.await_count == runner.MAX_ATTEMPTS
    assert [call.args[0] for call in sleep.await_args_list] == [2, 4]


def test_invalid_backend_and_missing_vertex_id_fail_clearly(monkeypatch):
    monkeypatch.setenv("AGENT_BACKEND", "typo")
    with pytest.raises(ValueError, match="local or vertex"):
        runner.selected_backend()
    monkeypatch.setattr(runner, "_remote_agent", None)
    monkeypatch.delenv("AGENT_ENGINE_ID", raising=False)
    with pytest.raises(RuntimeError, match="AGENT_ENGINE_ID"):
        runner._get_remote_agent()


def test_vertex_requires_shared_cloud_data(local_store, monkeypatch):
    monkeypatch.setattr(runner, "_remote_agent", None)
    monkeypatch.setenv(
        "AGENT_ENGINE_ID", "projects/project/locations/us-central1/reasoningEngines/123"
    )
    with pytest.raises(RuntimeError, match="CLAIMS_STORE=firestore"):
        runner._get_remote_agent()
    monkeypatch.setenv("CLAIMS_STORE", "firestore")
    monkeypatch.setenv("CLAIMS_EVIDENCE_BUCKET", "shared-evidence")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    with pytest.raises(RuntimeError, match="GOOGLE_CLOUD_PROJECT"):
        runner._get_remote_agent()


def test_error_events_raise_instead_of_returning_an_empty_reply(monkeypatch):
    async def events(*_args, **_kwargs):
        yield {
            "author": "auto_claims_intake_workflow",
            "error_code": "NOT_FOUND",
            "error_message": "Publisher model gemini-3.6-flash was not found",
        }

    monkeypatch.setattr(runner, "_events", events)
    with pytest.raises(runner.AgentTurnError, match="NOT_FOUND: Publisher model"):
        asyncio.run(runner.send_turn("u", "s", "hello", []))
