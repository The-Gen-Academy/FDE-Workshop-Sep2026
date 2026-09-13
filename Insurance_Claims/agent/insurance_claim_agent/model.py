"""Gemini model shared by every sub-agent in the workflow."""

import os
from functools import cached_property

from google.adk.models.google_llm import Gemini
from google.genai import Client

MODEL_NAME = "gemini-3.6-flash"
DEFAULT_MODEL_LOCATION = "global"


class ClaimsGemini(Gemini):
    """Gemini that calls Vertex AI's global endpoint instead of the runtime region.

    Agent Engine injects its own regional GOOGLE_CLOUD_LOCATION at runtime, but
    gemini-3.6-flash is only served from the global endpoint, so a plain
    ``Gemini(model=...)`` returns 404 NOT_FOUND on every turn once deployed.
    Override CLAIMS_MODEL_LOCATION to route model calls elsewhere; the Agent
    Engine resource itself stays regional.
    """

    @cached_property
    def api_client(self) -> Client:
        # Agent Engine sets this flag to "1"; local .env files usually use "TRUE".
        if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in {"1", "true"}:
            self.client_kwargs = {
                **(self.client_kwargs or {}),
                "vertexai": True,
                "location": os.environ.get("CLAIMS_MODEL_LOCATION", DEFAULT_MODEL_LOCATION),
            }
        return super().api_client


def claims_model() -> ClaimsGemini:
    return ClaimsGemini(model=MODEL_NAME)
