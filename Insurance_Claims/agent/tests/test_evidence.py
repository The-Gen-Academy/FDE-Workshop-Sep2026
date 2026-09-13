"""Evidence collection works for ADK web uploads and portal references."""

from types import SimpleNamespace

from google.genai import types
from insurance_claim_agent.evidence import collect_customer_photos


def content(*parts):
    return types.Content(role="user", parts=list(parts))


def context(events, current):
    invocation = SimpleNamespace(
        session=SimpleNamespace(id="test-session", events=events),
        user_content=current,
    )
    return SimpleNamespace(state={}, get_invocation_context=lambda: invocation)


def test_inline_images_across_turns_persist_once_and_ignore_model_images(monkeypatch):
    first = content(types.Part.from_bytes(data=b"photo one", mime_type="image/png"))
    second = content(types.Part.from_bytes(data=b"photo two", mime_type="image/jpeg"))
    ignored = content(types.Part.from_bytes(data=b"model photo", mime_type="image/png"))
    tool_context = context(
        [
            SimpleNamespace(author="user", content=first),
            SimpleNamespace(author="model", content=ignored),
        ],
        second,
    )
    saves = []

    def save(session_id, photo_id, data, mime):
        saves.append((session_id, photo_id, data, mime))
        return f"/photos/{session_id}/{photo_id}"

    monkeypatch.setattr("insurance_claim_agent.evidence.save_customer_photo", save)
    photos = collect_customer_photos(tool_context)
    assert len(photos) == 2
    assert [entry[2] for entry in saves] == [b"photo one", b"photo two"]
    assert [mime for _, mime in photos] == ["image/png", "image/jpeg"]
    assert collect_customer_photos(tool_context) == photos
    assert len(saves) == 2


def test_live_content_and_repeated_file_references_are_not_counted_twice():
    image = types.Part.from_uri(file_uri="gs://evidence/photos/one.jpg", mime_type="image/jpeg")
    document = types.Part.from_uri(
        file_uri="gs://evidence/docs/report.pdf", mime_type="application/pdf"
    )
    current = content(image, image, document)
    tool_context = context([SimpleNamespace(author="user", content=current)], current)
    assert collect_customer_photos(tool_context) == [
        ("gs://evidence/photos/one.jpg", "image/jpeg"),
    ]


def test_repeated_inline_bytes_use_one_reference(monkeypatch):
    photo = types.Part.from_bytes(data=b"same photo", mime_type="image/png")
    tool_context = context([], content(photo, photo))
    monkeypatch.setattr(
        "insurance_claim_agent.evidence.save_customer_photo",
        lambda session_id, photo_id, data, mime: f"/photos/{photo_id}",
    )
    assert len(collect_customer_photos(tool_context)) == 1
