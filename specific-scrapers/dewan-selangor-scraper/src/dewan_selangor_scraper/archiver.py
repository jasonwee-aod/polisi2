"""
Google Cloud Storage archiver.

Upload convention:
    gov-docs/<site_slug>/raw/<YYYY>/<MM>/<DD>/<sha256>_<original_filename>

Dedup rule: if sha256 already exists in state, caller reuses the existing
gcs_uri and skips this upload entirely.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Optional
from urllib.parse import urlparse

log = logging.getLogger(__name__)

try:
    from google.cloud import storage as _gcs  # type: ignore[import-untyped]

    _GCS_AVAILABLE = True
except ImportError:
    _GCS_AVAILABLE = False


# ── Helpers ───────────────────────────────────────────────────────────────────


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def gcs_object_path(site_slug: str, sha256: str, original_url: str) -> str:
    """
    Build the GCS object path for a raw file.

    Format: gov-docs/<site_slug>/raw/<YYYY>/<MM>/<DD>/<sha256>_<filename>

    For HTML article pages where the URL has no file extension, the filename
    is derived from the URL path slug with a .html extension appended.
    """
    now = datetime.now(timezone.utc)
    parsed_path = PurePosixPath(urlparse(original_url).path)
    name = parsed_path.name or "document"
    # Ensure HTML pages get a .html suffix so the object is recognisable
    if "." not in name:
        name = name + ".html"
    date_part = now.strftime("%Y/%m/%d")
    return f"gov-docs/{site_slug}/raw/{date_part}/{sha256}_{name}"


# ── Archiver ──────────────────────────────────────────────────────────────────


class GCSArchiver:
    """
    Uploads raw file bytes to Google Cloud Storage.

    In dry-run mode, no upload is performed; a synthetic gs:// URI is returned
    so the rest of the pipeline can generate complete records.jsonl output.
    """

    def __init__(self, bucket_name: str, dry_run: bool = False) -> None:
        self.bucket_name = bucket_name
        self.dry_run = dry_run
        self._bucket: Optional[object] = None

        if not dry_run:
            if not _GCS_AVAILABLE:
                raise ImportError(
                    "google-cloud-storage is not installed. "
                    "Run: pip install google-cloud-storage"
                )
            client = _gcs.Client()
            self._bucket = client.bucket(bucket_name)

    def upload(self, data: bytes, object_path: str, content_type: str) -> str:
        """
        Upload *data* to GCS at *object_path*.

        Returns the gs:// URI of the uploaded object.
        Caller is responsible for skipping duplicate uploads (check sha256 first).
        """
        gcs_uri = f"gs://{self.bucket_name}/{object_path}"

        if self.dry_run:
            log.info(
                {
                    "event": "dry_run_upload_skipped",
                    "gcs_uri": gcs_uri,
                    "size_bytes": len(data),
                }
            )
            return gcs_uri

        blob = self._bucket.blob(object_path)  # type: ignore[union-attr]
        blob.upload_from_string(data, content_type=content_type)
        log.info(
            {
                "event": "uploaded",
                "gcs_uri": gcs_uri,
                "size_bytes": len(data),
                "content_type": content_type,
            }
        )
        return gcs_uri
