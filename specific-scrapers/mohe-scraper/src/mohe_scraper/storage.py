"""Storage backend for archiving original documents."""

import hashlib
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


class StorageBackend(ABC):
    """Abstract base class for storage backends."""

    @abstractmethod
    def store(self, content: bytes, gcs_object_path: str) -> str:
        """
        Store content and return URI.

        Args:
            content: File content bytes
            gcs_object_path: Path within storage (e.g., gov-docs/mohe/raw/2026/02/27/sha256_file.pdf)

        Returns:
            URI/path of stored object
        """
        pass

    @abstractmethod
    def exists(self, gcs_object_path: str) -> bool:
        """Check if object already exists."""
        pass

    @staticmethod
    def compute_sha256(content: bytes) -> str:
        """Compute SHA256 hash of content."""
        return hashlib.sha256(content).hexdigest()


class LocalStorageBackend(StorageBackend):
    """Store files locally on filesystem."""

    def __init__(self, base_dir: str = "./data"):
        """
        Initialize local storage.

        Args:
            base_dir: Base directory for storing files
        """
        self.base_dir = Path(base_dir) / "documents"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"LocalStorageBackend initialized at {self.base_dir}")

    def store(self, content: bytes, gcs_object_path: str) -> str:
        """
        Store content locally.

        Args:
            content: File content bytes
            gcs_object_path: Path (used as relative path structure)

        Returns:
            Local file path
        """
        file_path = self.base_dir / gcs_object_path
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path, "wb") as f:
            f.write(content)

        logger.debug(f"Stored file locally: {file_path}")
        return str(file_path)

    def exists(self, gcs_object_path: str) -> bool:
        """Check if file exists locally."""
        file_path = self.base_dir / gcs_object_path
        return file_path.exists()


class GCSStorageBackend(StorageBackend):
    """Store files in Google Cloud Storage."""

    def __init__(self, bucket_name: str):
        """
        Initialize GCS storage.

        Args:
            bucket_name: GCS bucket name
        """
        try:
            from google.cloud import storage as gcs
            self.client = gcs.Client()
            self.bucket = self.client.bucket(bucket_name)
            self.bucket_name = bucket_name
            logger.info(f"GCSStorageBackend initialized with bucket: {bucket_name}")
        except ImportError:
            raise ImportError("google-cloud-storage not installed. Install with: pip install google-cloud-storage")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize GCS client: {e}")

    def store(self, content: bytes, gcs_object_path: str) -> str:
        """
        Store content in GCS.

        Args:
            content: File content bytes
            gcs_object_path: Path within bucket

        Returns:
            GCS URI (gs://bucket/path)
        """
        blob = self.bucket.blob(gcs_object_path)

        # Check if already exists to avoid re-uploading
        if blob.exists():
            logger.debug(f"Object already exists in GCS: {gcs_object_path}")
            return f"gs://{self.bucket_name}/{gcs_object_path}"

        # Upload to GCS
        blob.upload_from_string(content)
        logger.info(f"Uploaded to GCS: {gcs_object_path}")

        return f"gs://{self.bucket_name}/{gcs_object_path}"

    def exists(self, gcs_object_path: str) -> bool:
        """Check if object exists in GCS."""
        blob = self.bucket.blob(gcs_object_path)
        return blob.exists()


class StorageFactory:
    """Factory for creating storage backends based on configuration."""

    @staticmethod
    def create() -> StorageBackend:
        """
        Create storage backend based on environment.

        Uses GCS if GCS_BUCKET is set and credentials available,
        otherwise falls back to local storage.

        Returns:
            StorageBackend instance
        """
        gcs_bucket = os.getenv("GCS_BUCKET")

        if gcs_bucket:
            try:
                return GCSStorageBackend(gcs_bucket)
            except Exception as e:
                logger.warning(f"Failed to initialize GCS storage: {e}. Falling back to local storage.")

        base_dir = os.getenv("DATA_DIR", "./data")
        return LocalStorageBackend(base_dir)


def extract_metadata_from_response(
    response_headers: dict,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract ETag and Last-Modified from HTTP response headers.

    Args:
        response_headers: HTTP response headers dict

    Returns:
        Tuple of (etag, last_modified) or (None, None) if not present
    """
    etag = response_headers.get("ETag")
    last_modified = response_headers.get("Last-Modified")
    return etag, last_modified
