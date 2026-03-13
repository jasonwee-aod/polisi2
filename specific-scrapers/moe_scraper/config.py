from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class SiteConfig:
    site_slug: str
    base_url: str
    allowed_hosts: list[str]
    agency: str
    default_language: str
    parser_version: str
    feed_urls: list[str]
    sitemap_urls: list[str]
    section_urls: list[str]
    max_pages_default: int = 100
    same_domain_only: bool = True


def load_site_config(path: str | Path) -> SiteConfig:
    config_path = Path(path)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    return SiteConfig(**raw)
