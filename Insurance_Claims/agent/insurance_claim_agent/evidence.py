"""Collect customer images across ADK turns and persist inline uploads."""

from hashlib import sha256

from claims_core.evidence import save_customer_photo
from google.adk.tools import ToolContext


def collect_customer_photos(tool_context: ToolContext) -> list[tuple[str, str]]:
    """Return real image references in submission order, including this turn.

    Portals send file references; ADK web can send inline images. Cache inline
    references in session state so retries reuse the saved files.
    """
    invocation = tool_context.get_invocation_context()
    contents = [
        event.content
        for event in invocation.session.events
        if event.author == "user" and event.content
    ]
    if invocation.user_content and invocation.user_content not in contents:
        contents.append(invocation.user_content)

    saved = dict(tool_context.state.get("_inline_photo_refs") or {})
    photos = []
    seen_references = set()
    for content in contents:
        for part in content.parts or []:
            file_data = part.file_data
            inline_data = part.inline_data
            if (
                file_data
                and (file_data.mime_type or "").startswith("image/")
                and file_data.file_uri
            ):
                photo = (file_data.file_uri, file_data.mime_type)
            elif (
                inline_data
                and (inline_data.mime_type or "").startswith("image/")
                and inline_data.data
            ):
                key = sha256(inline_data.mime_type.encode() + inline_data.data).hexdigest()
                if key not in saved:
                    saved[key] = save_customer_photo(
                        invocation.session.id,
                        f"inline-{key}",
                        inline_data.data,
                        inline_data.mime_type,
                    )
                photo = (saved[key], inline_data.mime_type)
            else:
                continue
            if photo[0] not in seen_references:
                photos.append(photo)
                seen_references.add(photo[0])

    tool_context.state["_inline_photo_refs"] = saved
    return photos
