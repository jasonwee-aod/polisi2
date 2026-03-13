"""URL normalization and canonicalization utilities."""

from urllib.parse import urlparse, urlunparse, urljoin, quote, unquote
from typing import Optional
import re


class URLNormalizer:
    """Handles URL normalization and canonicalization."""

    def __init__(self, allowed_hosts: list[str]):
        """
        Initialize with allowed hosts.

        Args:
            allowed_hosts: List of allowed hostnames (e.g., ['www.mohe.gov.my', 'mohe.gov.my'])
        """
        self.allowed_hosts = [self._normalize_host(h) for h in allowed_hosts]

    @staticmethod
    def _normalize_host(host: str) -> str:
        """Normalize host by lowercasing."""
        return host.lower().strip()

    def is_allowed_host(self, url: str) -> bool:
        """Check if URL belongs to allowed hosts."""
        try:
            parsed = urlparse(url)
            host = self._normalize_host(parsed.netloc)

            # Handle www prefix variations
            base_host = host.replace("www.", "")
            allowed_base_hosts = [h.replace("www.", "") for h in self.allowed_hosts]

            return base_host in allowed_base_hosts
        except Exception:
            return False

    def canonicalize(self, url: str, base_url: Optional[str] = None) -> Optional[str]:
        """
        Canonicalize a URL to a standard form for deduplication.

        Steps:
        1. Convert to absolute URL if relative
        2. Use HTTPS
        3. Remove www prefix (consistent)
        4. Remove fragment
        5. Remove tracking parameters
        6. Sort query parameters
        7. Lowercase

        Args:
            url: URL to canonicalize
            base_url: Base URL for resolving relative URLs

        Returns:
            Canonicalized URL or None if not allowed
        """
        try:
            # Resolve relative URLs
            if base_url and not url.startswith("http"):
                url = urljoin(base_url, url)

            parsed = urlparse(url)

            # Check if host is allowed
            host = self._normalize_host(parsed.netloc)
            base_host = host.replace("www.", "")
            allowed_base_hosts = [h.replace("www.", "") for h in self.allowed_hosts]

            if base_host not in allowed_base_hosts:
                return None

            # Normalize scheme to https
            scheme = "https"

            # Remove www prefix for consistency
            netloc = host.replace("www.", "")

            # Decode and re-encode path to normalize percent-encoding
            path = quote(unquote(parsed.path), safe="/")

            # Remove fragment
            fragment = ""

            # Parse and clean query parameters
            params = {}
            if parsed.query:
                for param in parsed.query.split("&"):
                    if "=" in param:
                        key, value = param.split("=", 1)
                        # Remove tracking/session parameters
                        if not self._is_tracking_param(key):
                            params[key] = value

            # Sort query parameters for consistency
            query = "&".join(
                f"{k}={v}" for k, v in sorted(params.items())
            ) if params else ""

            # Reconstruct URL
            canonical = urlunparse((scheme, netloc, path, "", query, fragment))

            # Remove trailing slash for consistency (except for root)
            if canonical.endswith("/") and canonical.count("/") > 3:  # 3 = scheme + domain + root slash
                canonical = canonical.rstrip("/")

            return canonical.lower()

        except Exception:
            return None

    @staticmethod
    def _is_tracking_param(param_name: str) -> bool:
        """Identify and filter tracking/session parameters."""
        tracking_params = {
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_content",
            "utm_term",
            "fbclid",
            "gclid",
            "msclkid",
            "sessionid",
            "phpsessid",
            "jsessionid",
            "_ga",
        }
        return param_name.lower() in tracking_params


class URLExtractor:
    """Extract and normalize URLs from various sources."""

    @staticmethod
    def extract_absolute_url(url: str, base_url: str) -> str:
        """Convert relative URL to absolute."""
        return urljoin(base_url, url)

    @staticmethod
    def extract_filename_from_url(url: str) -> str:
        """Extract filename from URL path."""
        parsed = urlparse(url)
        path = parsed.path
        if "/" in path:
            return path.split("/")[-1]
        return path or "document"

    @staticmethod
    def get_content_type_from_url(url: str) -> str:
        """Infer content type from URL extension."""
        extension_map = {
            ".pdf": "application/pdf",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xls": "application/vnd.ms-excel",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".ppt": "application/vnd.ms-powerpoint",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".zip": "application/zip",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
        }

        url_lower = url.lower()
        for ext, mime_type in extension_map.items():
            if url_lower.endswith(ext):
                return mime_type

        return "text/html"  # Default
