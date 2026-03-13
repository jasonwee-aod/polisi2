"""URL normalization and validation."""
from urllib.parse import urlparse, urlunparse
from typing import Optional


def canonicalize_url(url: str, allowed_hosts: Optional[list] = None) -> Optional[str]:
    """
    Normalize URL to canonical form.
    - Force https
    - Remove trailing slashes
    - Validate host is in allowed list
    """
    if not url or not isinstance(url, str):
        return None

    try:
        parsed = urlparse(url)

        # Validate scheme
        if parsed.scheme not in ("http", "https", ""):
            return None

        # Extract hostname
        hostname = parsed.hostname
        if not hostname:
            return None

        # Remove www prefix for comparison
        hostname_normalized = hostname.replace("www.", "")

        # Check allowed hosts if provided
        if allowed_hosts:
            allowed_normalized = [h.replace("www.", "") for h in allowed_hosts]
            if hostname_normalized not in allowed_normalized:
                return None

        # Rebuild with https
        canonical = urlunparse((
            "https",
            hostname,  # keep original hostname
            parsed.path.rstrip("/") or "/",
            "",  # params
            parsed.query,
            ""  # fragment
        ))

        return canonical
    except Exception:
        return None


def is_same_domain(url1: str, url2: str) -> bool:
    """Check if two URLs are from same domain."""
    try:
        host1 = urlparse(url1).hostname
        host2 = urlparse(url2).hostname
        return host1 == host2
    except Exception:
        return False


def extract_absolute_url(relative_url: str, base_url: str) -> Optional[str]:
    """Convert relative URL to absolute using base URL."""
    if not relative_url or not base_url:
        return None

    try:
        if relative_url.startswith("http://") or relative_url.startswith("https://"):
            return relative_url

        base_parsed = urlparse(base_url)

        if relative_url.startswith("/"):
            # Absolute path
            return urlunparse((
                base_parsed.scheme,
                base_parsed.netloc,
                relative_url,
                "",
                "",
                ""
            ))
        else:
            # Relative path
            base_path = base_parsed.path.rstrip("/")
            if not base_path or base_path == "":
                base_path = ""
            new_path = f"{base_path}/{relative_url}".replace("//", "/")
            return urlunparse((
                base_parsed.scheme,
                base_parsed.netloc,
                new_path,
                "",
                "",
                ""
            ))
    except Exception:
        return None
