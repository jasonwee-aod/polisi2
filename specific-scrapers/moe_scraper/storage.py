from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path

import boto3  # type: ignore

from moe_scraper.utils import make_spaces_object_path

# Only these extensions are supported by the Polisi indexing manifest.
_INDEXABLE_EXTENSIONS = {".html", ".pdf", ".docx", ".xlsx"}


@dataclass(slots=True)
class UploadResult:
    bucket: str
    object_path: str
    uri: str


class DoSpacesArchiver:
    def __init__(self, bucket_name: str, region: str, endpoint: str, key: str, secret: str) -> None:
        self.bucket_name = bucket_name
        self.client = boto3.client(
            "s3",
            region_name=region,
            endpoint_url=endpoint,
            aws_access_key_id=key,
            aws_secret_access_key=secret,
        )

    def upload_bytes(
        self,
        site_slug: str,
        sha256: str,
        original_filename: str,
        payload: bytes,
        fetched_at: str,
        content_type: str | None,
        source_url: str | None = None,
    ) -> UploadResult | None:
        """Upload payload to DO Spaces.

        Returns None (skipping the file) when the file type is not supported
        by the indexing manifest.  HTML responses whose URL path lacks an
        extension are stored as ``.html`` automatically.
        """
        p = Path(original_filename)
        ext = p.suffix.lower()

        # Assign .html extension to extension-less HTML responses.
        if not ext and content_type and "html" in content_type:
            original_filename = (p.stem or "document") + ".html"
            ext = ".html"

        if ext not in _INDEXABLE_EXTENSIONS:
            return None

        object_path = make_spaces_object_path(sha256, original_filename, fetched_at)
        guessed_type = (
            content_type
            or mimetypes.guess_type(original_filename)[0]
            or "application/octet-stream"
        )
        metadata: dict[str, str] = {"sha256": sha256}
        if source_url:
            metadata["source_url"] = source_url
        self.client.put_object(
            Bucket=self.bucket_name,
            Key=object_path,
            Body=payload,
            ContentType=guessed_type,
            Metadata=metadata,
        )
        return UploadResult(
            bucket=self.bucket_name,
            object_path=object_path,
            uri=f"s3://{self.bucket_name}/{object_path}",
        )
