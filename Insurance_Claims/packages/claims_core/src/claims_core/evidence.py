"""Store photo bytes independently of the database used for claim records."""

import mimetypes
import re
from pathlib import Path

from .config import evidence_bucket, evidence_prefix, local_data_dir

_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
}


def save_customer_photo(session_id: str, index: int | str, data: bytes, mime_type: str) -> str:
    """Return a gs:// URI or local absolute path for the stored image."""
    if not re.fullmatch(r"[\w-]+", session_id) or not re.fullmatch(r"[\w-]+", str(index)):
        raise ValueError("Invalid evidence session or image ID")
    ext = _EXTENSIONS.get(mime_type) or mimetypes.guess_extension(mime_type)
    if not mime_type.startswith("image/") or not ext:
        raise ValueError("Evidence must have a supported image MIME type")
    relative = f"photos/{session_id}/{index}{ext}"
    bucket = evidence_bucket()
    if bucket:
        from google.cloud import storage

        name = "/".join(part for part in (evidence_prefix(), relative) if part)
        storage.Client().bucket(bucket).blob(name).upload_from_string(data, content_type=mime_type)
        return f"gs://{bucket}/{name}"
    path = local_data_dir() / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


def load_photo(ref: str) -> bytes:
    """Read stored evidence from the configured bucket or local photo directory."""
    if ref.startswith("gs://"):
        from google.cloud import storage

        bucket, separator, name = ref[5:].partition("/")
        prefix = "/".join(part for part in (evidence_prefix(), "photos/") if part)
        if not separator or bucket != evidence_bucket() or not name.startswith(prefix):
            raise ValueError("Photo reference is outside the configured evidence bucket/prefix")
        return storage.Client().bucket(bucket).blob(name).download_as_bytes()
    path = Path(ref).resolve()
    if not path.is_relative_to((local_data_dir() / "photos").resolve()):
        raise ValueError("Photo reference is outside the local evidence directory")
    return path.read_bytes()
