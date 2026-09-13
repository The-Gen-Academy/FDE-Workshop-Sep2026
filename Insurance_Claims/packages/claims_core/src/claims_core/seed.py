"""Explicit, non-overwriting imports of sample or legacy claim collections."""

import argparse
import copy
import json
import mimetypes
import os
from hashlib import sha256
from pathlib import Path

from .config import load_environment
from .storage import get_store

COLLECTIONS = (
    "policies",
    "claim_history",
    "parts_pricing",
    "vin_claims",
    "escalations",
    "claims_log",
    "client_sessions",
)


def read_seed(source: Path) -> dict[str, dict]:
    if not source.is_dir():
        raise ValueError(f"Seed directory does not exist: {source}")
    collections = {
        name: json.loads((source / f"{name}.json").read_text(encoding="utf-8"))
        for name in COLLECTIONS
        if (source / f"{name}.json").is_file()
    }
    if not collections:
        raise ValueError(f"No recognized collection JSON files found in {source}")
    return collections


def read_gcs(bucket: str, prefix: str) -> dict[str, dict]:
    """Read only the known legacy collection objects; never mutate the source."""
    from google.api_core.exceptions import NotFound
    from google.cloud import storage

    source = storage.Client().bucket(bucket)
    collections = {}
    for name in COLLECTIONS:
        try:
            collections[name] = json.loads(source.blob(f"{prefix}{name}.json").download_as_bytes())
        except NotFound:
            continue
    if not collections:
        raise ValueError("No recognized collection JSON objects found at the source")
    return collections


def validate(collections: dict[str, dict]) -> None:
    """Validate every record before writing any destination documents."""
    from .storage import _name

    for name, documents in collections.items():
        _name(name)
        if not isinstance(documents, dict):
            raise ValueError(f"{name} must be an object keyed by document ID")
        for doc_id, fields in documents.items():
            _name(doc_id)
            if not isinstance(fields, dict):
                raise ValueError(f"{name}/{doc_id} must be a JSON object")
            # Native Firestore documents are limited to 1 MiB, including field overhead.
            if len(json.dumps(fields, allow_nan=False).encode()) > 900_000:
                raise ValueError(f"{name}/{doc_id} is too large; split it before importing")


def import_records(collections: dict[str, dict], store) -> dict:
    """Create missing documents atomically per record. A rerun safely skips existing IDs."""
    validate(collections)
    counts = {"created": 0, "skipped": 0}
    for collection, documents in collections.items():
        for doc_id, fields in documents.items():

            def create(tx):
                if tx.get(collection, doc_id) is not None:
                    return "skipped"
                tx.set(collection, doc_id, fields)
                return "created"

            counts[store.atomic(create)] += 1
    return counts


def seed_photo_files(collections: dict, source: Path) -> dict[str, Path]:
    """Resolve historical local photo references against the supplied seed directory."""
    root = (source / "photos").resolve()
    files = {}
    for documents in collections.values():
        for fields in documents.values():
            for ref in (fields.get("evidence") or {}).get("photo_refs", []):
                if ref.startswith("gs://"):
                    continue
                parts = [part for part in ref.replace("\\", "/").split("/") if part]
                if "photos" not in parts:
                    raise ValueError(f"Cannot locate bundled photo: {ref}")
                path = root.joinpath(*parts[parts.index("photos") + 1 :]).resolve()
                if not path.is_relative_to(root) or not path.is_file():
                    raise ValueError(f"Bundled photo is missing or outside photos/: {ref}")
                files[ref] = path
    return files


def copy_seed_photos(collections: dict, files: dict[str, Path]) -> dict:
    """Copy bundled photos and rewrite only the records being imported."""
    from .evidence import save_customer_photo

    references = {}
    for ref, path in files.items():
        data = path.read_bytes()
        references[ref] = save_customer_photo(
            "seed",
            sha256(data).hexdigest(),
            data,
            mimetypes.guess_type(path.name)[0] or "image/jpeg",
        )
    updated = copy.deepcopy(collections)
    for documents in updated.values():
        for fields in documents.values():
            evidence = fields.get("evidence") or {}
            if "photo_refs" in evidence:
                evidence["photo_refs"] = [
                    references.get(ref, ref) for ref in evidence["photo_refs"]
                ]
    return updated


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    seed = subcommands.add_parser("seed", help="Import collection JSON files")
    seed.add_argument("--source", type=Path, default=Path("data/seed"))
    seed.add_argument(
        "--with-evidence",
        action="store_true",
        help="Copy bundled photos and rewrite imported references",
    )
    legacy = subcommands.add_parser("import-gcs", help="Read legacy JSON objects from GCS")
    legacy.add_argument("--bucket", required=True)
    legacy.add_argument("--prefix", default="", help="Exact prefix before collection filenames")
    for command in (seed, legacy):
        command.add_argument(
            "--apply", action="store_true", help="Create missing destination records"
        )
    args = parser.parse_args(argv)
    load_environment()
    collections = (
        read_seed(args.source) if args.command == "seed" else read_gcs(args.bucket, args.prefix)
    )
    validate(collections)
    files = (
        seed_photo_files(collections, args.source)
        if args.command == "seed" and args.with_evidence
        else {}
    )
    summary = {
        "mode": "apply" if args.apply else "dry-run",
        "destination": os.environ.get("CLAIMS_STORE", "local"),
        "collections": {name: len(documents) for name, documents in collections.items()},
        "evidence": f"{len(files)} bundled photos"
        if files
        else "References only; image files are not copied or uploaded",
    }
    if args.apply:
        if files:
            collections = copy_seed_photos(collections, files)
        summary.update(import_records(collections, get_store()))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
