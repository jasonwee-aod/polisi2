"""Manifest loading for raw corpus objects stored in DigitalOcean Spaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from polisi_scraper.config import ScraperSettings


class ManifestError(ValueError):
    """Raised when the raw corpus manifest cannot normalize an object key."""


class SpacesManifestClient(Protocol):
    """Minimal S3-compatible client surface used by the manifest loader."""

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        """Return an S3 list_objects_v2 style payload."""


@dataclass(frozen=True)
class SpacesObject:
    """Normalized object metadata emitted from Spaces listings."""

    storage_path: str
    agency: str
    year_month: str
    filename: str
    file_type: str
    version_token: str
    size_bytes: int | None = None
    last_modified: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def title(self) -> str:
        return Path(self.filename).stem.replace("_", " ").strip() or self.filename


@dataclass(frozen=True)
class PendingIndexItem:
    """Parse-ready work item produced by the manifest."""

    storage_path: str
    agency: str
    year_month: str
    filename: str
    file_type: str
    version_token: str
    title: str
    source_url: str | None = None
    size_bytes: int | None = None
    last_modified: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class SpacesCorpusManifest:
    """Enumerates raw corpus objects and filters out already-indexed versions."""

    def __init__(
        self,
        settings: ScraperSettings,
        *,
        client: SpacesManifestClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client

    def list_objects(self) -> list[SpacesObject]:
        client = self._ensure_client()
        continuation_token: str | None = None
        objects: list[SpacesObject] = []

        while True:
            request: dict[str, object] = {
                "Bucket": self._settings.do_spaces_bucket,
                "Prefix": self._settings.indexer_spaces_prefix,
            }
            if continuation_token:
                request["ContinuationToken"] = continuation_token
            response = client.list_objects_v2(**request)
            for raw_object in response.get("Contents", []):
                objects.append(self._normalize_object(raw_object))
            if not response.get("IsTruncated"):
                break
            continuation_token = response.get("NextContinuationToken")

        return sorted(objects, key=lambda item: item.storage_path)

    def pending_items(self, fingerprints: "IndexedFingerprintStore") -> list[PendingIndexItem]:
        pending: list[PendingIndexItem] = []
        for obj in self.list_objects():
            if fingerprints.has_fingerprint(obj.storage_path, obj.version_token):
                continue
            pending.append(
                PendingIndexItem(
                    storage_path=obj.storage_path,
                    agency=obj.agency,
                    year_month=obj.year_month,
                    filename=obj.filename,
                    file_type=obj.file_type,
                    version_token=obj.version_token,
                    title=obj.title,
                    size_bytes=obj.size_bytes,
                    last_modified=obj.last_modified,
                    metadata=dict(obj.metadata),
                    source_url=_as_optional_str(obj.metadata.get("source_url")),
                )
            )
        return pending

    def _ensure_client(self) -> SpacesManifestClient:
        if self._client is not None:
            return self._client

        try:
            import boto3  # type: ignore
        except ImportError as exc:
            raise RuntimeError("boto3 is required for Spaces manifest loading") from exc

        self._client = boto3.client(
            "s3",
            region_name=self._settings.do_spaces_region,
            endpoint_url=self._settings.do_spaces_endpoint,
            aws_access_key_id=self._settings.do_spaces_key,
            aws_secret_access_key=self._settings.do_spaces_secret,
        )
        return self._client

    def _normalize_object(self, raw_object: dict[str, Any]) -> SpacesObject:
        key = raw_object["Key"]
        parts = key.split("/")
        if len(parts) != 4 or parts[0] != "gov-my":
            raise ManifestError(f"Unsupported storage path: {key}")

        filename = parts[3]
        suffix = Path(filename).suffix.lower()
        if suffix not in {".html", ".pdf", ".docx", ".xlsx"}:
            raise ManifestError(f"Unsupported file type in storage path: {key}")

        metadata = _normalize_metadata(raw_object.get("Metadata"))
        version_token = (
            metadata.get("sha256")
            or _as_optional_str(raw_object.get("VersionId"))
            or _clean_etag(raw_object.get("ETag"))
            or key
        )
        return SpacesObject(
            storage_path=key,
            agency=parts[1],
            year_month=parts[2],
            filename=filename,
            file_type=suffix.lstrip("."),
            version_token=str(version_token),
            size_bytes=_as_optional_int(raw_object.get("Size")),
            last_modified=raw_object.get("LastModified"),
            metadata=metadata,
        )


def _normalize_metadata(raw_metadata: Any) -> dict[str, object]:
    if not raw_metadata:
        return {}
    if not isinstance(raw_metadata, dict):
        raise ManifestError(f"Unsupported object metadata: {raw_metadata!r}")
    return {str(key): value for key, value in raw_metadata.items()}


def _clean_etag(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip("\"") or None


def _as_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


from polisi_scraper.indexer.state import IndexedFingerprintStore
