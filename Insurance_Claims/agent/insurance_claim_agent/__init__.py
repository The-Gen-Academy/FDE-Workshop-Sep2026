"""ADK-discoverable insurance claims agent."""

from claims_core.config import load_environment

load_environment()

from . import agent as agent  # noqa: E402
