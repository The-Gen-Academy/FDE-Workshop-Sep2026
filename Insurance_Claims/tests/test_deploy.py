"""Check the deployment boundary without calling Google Cloud."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def deploy_module(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "agent/deploy.py"
    spec = importlib.util.spec_from_file_location("claims_deploy", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "build_bundle", lambda: (tmp_path, []))
    return module


def test_default_dry_run_never_initializes_cloud(deploy_module, monkeypatch, capsys):
    import vertexai
    from google.cloud import storage
    from vertexai import agent_engines

    def unexpected(*args, **kwargs):
        pytest.fail("Dry-run attempted a cloud operation")

    monkeypatch.setattr(vertexai, "init", unexpected)
    monkeypatch.setattr(storage, "Client", unexpected)
    monkeypatch.setattr(agent_engines, "create", unexpected)
    monkeypatch.delenv("CLAIMS_EVIDENCE_PREFIX", raising=False)
    monkeypatch.setenv("CLAIMS_GCS_PREFIX", "legacy/")
    deploy_module.main([])
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "dry-run"
    assert output["serialization"] == "passed"
    assert output["runtime_environment"]["CLAIMS_EVIDENCE_PREFIX"] == "legacy"


def test_deploy_rejects_missing_staging_bucket_before_sdk_create(deploy_module, monkeypatch):
    from google.api_core.exceptions import NotFound
    from google.cloud import storage
    from vertexai import agent_engines

    client = MagicMock()
    client.get_bucket.side_effect = NotFound("missing bucket")
    monkeypatch.setattr(storage, "Client", lambda **kwargs: client)
    create = MagicMock()
    monkeypatch.setattr(agent_engines, "create", create)
    with pytest.raises(NotFound):
        deploy_module.main(
            [
                "--deploy",
                "--project",
                "test-project",
                "--staging-bucket",
                "gs://missing",
                "--evidence-bucket",
                "evidence",
                "--service-account",
                "agent@test.invalid",
            ]
        )
    client.get_bucket.assert_called_once_with("missing")
    create.assert_not_called()
