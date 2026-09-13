"""Environment configuration shared by local apps and the agent."""

import os
from pathlib import Path

from dotenv import load_dotenv


def workspace_root() -> Path:
    """Find the source checkout; installed distributions fall back to the cwd."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "agent/pyproject.toml").is_file() and (parent / "local_apps").is_dir():
            return parent
    return Path.cwd()


def load_environment() -> None:
    """Load the local .env without overriding exported or cloud runtime settings."""
    explicit = os.environ.get("CLAIMS_ENV_FILE")
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"CLAIMS_ENV_FILE does not exist: {path}")
    else:
        path = workspace_root() / ".env"
    load_dotenv(path, override=False)


def local_data_dir() -> Path:
    configured = os.environ.get("CLAIMS_DATA_DIR")
    path = Path(configured).expanduser() if configured else Path(".local/data")
    return (workspace_root() / path).resolve()


def evidence_bucket() -> str | None:
    """Accept the old bucket variable for evidence, never for structured records."""
    return os.environ.get("CLAIMS_EVIDENCE_BUCKET") or os.environ.get("CLAIMS_GCS_BUCKET")


def evidence_prefix() -> str:
    return os.environ.get("CLAIMS_EVIDENCE_PREFIX", os.environ.get("CLAIMS_GCS_PREFIX", "")).strip(
        "/"
    )
