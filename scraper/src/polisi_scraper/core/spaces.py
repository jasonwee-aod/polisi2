"""DO Spaces helpers and uploader abstraction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import mimetypes
from typing import Any

from polisi_scraper.core.dedup import build_versioned_filename


@dataclass(frozen=True)
class SpacesConfig:
    key: str
    secret: str
    bucket: str
    region: str
    endpoint: str


class SpacesUploader:
    def __init__(self, config: SpacesConfig, boto3_client: Any | None = None) -> None:
        self._config = config
        self._client = boto3_client

    @property
    def bucket(self) -> str:
        return self._config.bucket

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client

        try:
            import boto3  # type: ignore
        except ImportError as exc:
            raise RuntimeError("boto3 is required for Spaces uploads") from exc

        self._client = boto3.client(
            "s3",
            region_name=self._config.region,
            endpoint_url=self._config.endpoint,
            aws_access_key_id=self._config.key,
            aws_secret_access_key=self._config.secret,
        )
        return self._client

    def upload_bytes(self, data: bytes, object_key: str, content_type: str | None = None) -> str:
        client = self._ensure_client()
        guessed = content_type or mimetypes.guess_type(object_key)[0] or "application/octet-stream"
        client.put_object(
            Bucket=self._config.bucket,
            Key=object_key,
            Body=data,
            ContentType=guessed,
        )
        return object_key


def build_spaces_key(
    *,
    agency: str,
    year_month: str,
    filename: str,
    changed_on: date | None = None,
) -> str:
    normalized_agency = "-".join(filter(None, _normalize_token(agency).split("-")))
    stable_filename = build_versioned_filename(filename, changed_on)
    return f"gov-my/{normalized_agency}/{year_month}/{stable_filename}"


def _normalize_token(value: str) -> str:
    chars: list[str] = []
    for ch in value.lower().strip():
        if ch.isalnum():
            chars.append(ch)
        else:
            chars.append("-")
    return "".join(chars).strip("-")
