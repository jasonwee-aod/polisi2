"""DigitalOcean Spaces integration for archiving documents."""
import os
import hashlib
import logging
from datetime import datetime
from pathlib import Path
import boto3
from botocore.exceptions import ClientError


logger = logging.getLogger(__name__)


class SpacesArchive:
    """Upload and manage files in DigitalOcean Spaces."""

    def __init__(
        self,
        bucket: str = None,
        key: str = None,
        secret: str = None,
        region: str = None,
        endpoint: str = None,
    ):
        self.bucket = bucket or os.getenv("DO_SPACES_BUCKET")
        key = key or os.getenv("DO_SPACES_KEY")
        secret = secret or os.getenv("DO_SPACES_SECRET")
        region = region or os.getenv("DO_SPACES_REGION", "sgp1")
        endpoint = endpoint or os.getenv("DO_SPACES_ENDPOINT", f"https://{region}.digitaloceanspaces.com")

        if not all([self.bucket, key, secret]):
            raise ValueError("Missing Spaces credentials (DO_SPACES_BUCKET, DO_SPACES_KEY, DO_SPACES_SECRET)")

        self.region = region
        self.endpoint = endpoint
        self.client = boto3.client(
            "s3",
            region_name=region,
            endpoint_url=endpoint,
            aws_access_key_id=key,
            aws_secret_access_key=secret,
        )

    def upload_file(
        self,
        file_bytes: bytes,
        original_filename: str,
        content_type: str,
        agency: str = "perpaduan",
    ) -> dict:
        """
        Upload file to Spaces.
        Returns dict with spaces_path and spaces_url.
        """
        try:
            # Compute SHA256
            sha256 = hashlib.sha256(file_bytes).hexdigest()

            # Build spaces path: gov-my/agency/YYYY-MM/sha256_filename
            now = datetime.utcnow()
            year_month = now.strftime("%Y-%m")
            file_ext = Path(original_filename).suffix
            spaces_filename = f"{sha256}{file_ext}"
            spaces_path = f"gov-my/{agency}/{year_month}/{spaces_filename}"

            # Upload
            self.client.put_object(
                Bucket=self.bucket,
                Key=spaces_path,
                Body=file_bytes,
                ContentType=content_type,
                CacheControl="public, max-age=31536000",
                Metadata={
                    "original_name": original_filename,
                    "uploaded_at": now.isoformat() + "Z",
                }
            )

            spaces_url = f"https://{self.bucket}.{self.region}.digitaloceanspaces.com/{spaces_path}"

            logger.info(f"Uploaded {spaces_path}")

            return {
                "sha256": sha256,
                "spaces_path": spaces_path,
                "spaces_url": spaces_url,
            }

        except ClientError as e:
            logger.error(f"Failed to upload {original_filename}: {e}")
            raise

    def file_exists(self, spaces_path: str) -> bool:
        """Check if file already exists in Spaces."""
        try:
            self.client.head_object(Bucket=self.bucket, Key=spaces_path)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise
