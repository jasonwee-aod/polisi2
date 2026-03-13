"""
DigitalOcean Spaces archiver (S3-compatible via boto3).

Upload convention:
    gov-docs/<site_slug>/raw/<YYYY>/<MM>/<DD>/<sha256>_<original_filename>

Dedup rule: if sha256 already exists in state, caller reuses the existing
spaces_url and skips this upload entirely.

Required environment variables:
    DO_SPACES_KEY      – Spaces access key
    DO_SPACES_SECRET   – Spaces secret key
    DO_SPACES_BUCKET   – Bucket (Space) name
    DO_SPACES_REGION   – Region slug, e.g. "sgp1"
    DO_SPACES_ENDPOINT – Full endpoint URL, e.g. "https://sgp1.digitaloceanspaces.com"
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
    import boto3  # type: ignore[import-untyped]
    from botocore.exceptions import ClientError  # type: ignore[import-untyped]

    _BOTO3_AVAILABLE = True
except ImportError:
    _BOTO3_AVAILABLE = False


# ── Helpers ───────────────────────────────────────────────────────────────────


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def spaces_object_path(site_slug: str, sha256: str, original_url: str) -> str:
    """
    Build the Spaces object path for a raw file.

    Format: gov-docs/<site_slug>/raw/<YYYY>/<MM>/<DD>/<sha256>_<filename>

    For HTML article pages where the URL has no file extension, the filename
    is derived from the URL path slug with a .html extension appended.
    """
    now = datetime.now(timezone.utc)
    parsed_path = PurePosixPath(urlparse(original_url).path)
    name = parsed_path.name or "document"
    if "." not in name:
        name = name + ".html"
    date_part = now.strftime("%Y/%m/%d")
    return f"gov-docs/{site_slug}/raw/{date_part}/{sha256}_{name}"


def spaces_public_url(bucket: str, region: str, object_path: str) -> str:
    """Build the public HTTPS URL for an object in DigitalOcean Spaces."""
    return f"https://{bucket}.{region}.digitaloceanspaces.com/{object_path}"


# ── Archiver ──────────────────────────────────────────────────────────────────


class SpacesArchiver:
    """
    Uploads raw file bytes to DigitalOcean Spaces.

    In dry-run mode, no upload is performed; a synthetic https:// URL is
    returned so the rest of the pipeline can generate complete records.jsonl.
    """

    def __init__(
        self,
        bucket_name: str,
        region: str,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        dry_run: bool = False,
    ) -> None:
        self.bucket_name = bucket_name
        self.region = region
        self.dry_run = dry_run
        self._client: Optional[object] = None

        if not dry_run:
            if not _BOTO3_AVAILABLE:
                raise ImportError(
                    "boto3 is not installed. Run: pip install boto3"
                )
            self._client = boto3.client(
                "s3",
                region_name=region,
                endpoint_url=endpoint_url,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
            )

    def upload(self, data: bytes, object_path: str, content_type: str) -> str:
        """
        Upload *data* to Spaces at *object_path*.

        Returns the public HTTPS URL of the uploaded object.
        Caller is responsible for skipping duplicate uploads (check sha256 first).
        """
        url = spaces_public_url(self.bucket_name, self.region, object_path)

        if self.dry_run:
            log.info(
                {
                    "event": "dry_run_upload_skipped",
                    "spaces_url": url,
                    "size_bytes": len(data),
                }
            )
            return url

        self._client.put_object(  # type: ignore[union-attr]
            Bucket=self.bucket_name,
            Key=object_path,
            Body=data,
            ContentType=content_type,
            ACL="private",
        )
        log.info(
            {
                "event": "uploaded",
                "spaces_url": url,
                "size_bytes": len(data),
                "content_type": content_type,
            }
        )
        return url
