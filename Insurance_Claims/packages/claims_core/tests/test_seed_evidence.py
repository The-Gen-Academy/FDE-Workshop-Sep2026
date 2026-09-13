import json
from unittest.mock import MagicMock, patch

import pytest
from claims_core import evidence, seed
from claims_core.storage import LocalStore


def test_import_is_non_overwriting_and_repeatable(tmp_path):
    store = LocalStore(tmp_path)
    records = {"policies": {"P1": {"limit": 20}}}
    assert seed.import_records(records, store) == {"created": 1, "skipped": 0}
    assert seed.import_records({"policies": {"P1": {"limit": 0}}}, store) == {
        "created": 0,
        "skipped": 1,
    }
    assert store.read("policies", "P1")["limit"] == 20


def test_seed_dry_run_never_opens_destination(tmp_path, monkeypatch, capsys):
    (tmp_path / "policies.json").write_text(json.dumps({"P1": {"limit": 20}}))
    monkeypatch.setattr(seed, "get_store", lambda: pytest.fail("Dry-run opened the destination"))
    seed.main(["seed", "--source", str(tmp_path)])
    assert json.loads(capsys.readouterr().out)["mode"] == "dry-run"


def test_import_validates_every_record_before_writing(tmp_path):
    store = LocalStore(tmp_path)
    with pytest.raises(ValueError):
        seed.import_records({"policies": {"P1": {"limit": 20}, "P2": []}}, store)
    assert store.read("policies", "P1") is None


def test_local_evidence_stays_separate_from_records(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("CLAIMS_EVIDENCE_BUCKET", raising=False)
    monkeypatch.delenv("CLAIMS_GCS_BUCKET", raising=False)
    ref = evidence.save_customer_photo("session-1", 0, b"test-image", "image/png")
    assert evidence.load_photo(ref) == b"test-image"
    with pytest.raises(ValueError):
        evidence.load_photo(str(tmp_path / "private.txt"))
    with pytest.raises(ValueError):
        evidence.save_customer_photo("../outside", 0, b"test", "image/png")


def test_gcs_evidence_does_not_select_a_record_backend(monkeypatch):
    monkeypatch.setenv("CLAIMS_EVIDENCE_BUCKET", "test-evidence")
    monkeypatch.setenv("CLAIMS_EVIDENCE_PREFIX", "dev/")
    client = MagicMock()
    with patch("google.cloud.storage.Client", return_value=client):
        ref = evidence.save_customer_photo("session-1", 0, b"test-image", "image/png")
        assert ref == "gs://test-evidence/dev/photos/session-1/0.png"
        client.bucket.assert_called_with("test-evidence")
        client.bucket.return_value.blob.return_value.upload_from_string.assert_called_once_with(
            b"test-image", content_type="image/png"
        )
        with pytest.raises(ValueError):
            evidence.load_photo("gs://unrelated-bucket/dev/photos/session-1/0.png")


def test_seed_rebases_bundled_photos_without_changing_source(tmp_path, monkeypatch):
    source = tmp_path / "seed"
    photo = source / "photos/C1/0.png"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b"sample-image")
    old_ref = r"C:\old\local_data\photos\C1\0.png"
    records = {"escalations": {"C1": {"evidence": {"photo_refs": [old_ref]}}}}
    monkeypatch.setenv("CLAIMS_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.delenv("CLAIMS_EVIDENCE_BUCKET", raising=False)
    monkeypatch.delenv("CLAIMS_GCS_BUCKET", raising=False)
    files = seed.seed_photo_files(records, source)
    updated = seed.copy_seed_photos(records, files)
    new_ref = updated["escalations"]["C1"]["evidence"]["photo_refs"][0]
    assert new_ref != old_ref
    assert evidence.load_photo(new_ref) == b"sample-image"
    assert records["escalations"]["C1"]["evidence"]["photo_refs"] == [old_ref]


def test_evidence_seed_dry_run_does_not_copy_or_open_store(tmp_path, monkeypatch):
    (tmp_path / "escalations.json").write_text(json.dumps({"C1": {"evidence": {"photo_refs": []}}}))
    monkeypatch.setattr(
        seed, "copy_seed_photos", lambda *args: pytest.fail("Dry-run copied photos")
    )
    monkeypatch.setattr(seed, "get_store", lambda: pytest.fail("Dry-run opened destination"))
    seed.main(["seed", "--source", str(tmp_path), "--with-evidence"])
