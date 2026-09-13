"""Request/response models for the client portal API."""

from pydantic import BaseModel


class StartSessionRequest(BaseModel):
    policy_number: str = ""


class StartSessionResponse(BaseModel):
    session_id: str
    policy_number: str


class MessageResponse(BaseModel):
    reply_text: str
    claim_id: str | None = None
    needs_more_photos: str | None = None
    outcome: dict | None = None
    rate_limited: bool = False
