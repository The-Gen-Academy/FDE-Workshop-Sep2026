import pytest
from claims_core.storage import get_store


@pytest.fixture
def local_store(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMS_STORE", "local")
    monkeypatch.setenv("CLAIMS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AGENT_BACKEND", "local")
    monkeypatch.delenv("CLAIMS_EVIDENCE_BUCKET", raising=False)
    monkeypatch.delenv("CLAIMS_GCS_BUCKET", raising=False)
    get_store.cache_clear()
    yield get_store()
    get_store.cache_clear()
