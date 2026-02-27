"""Adapter registry and discovery utilities."""

from __future__ import annotations

from typing import Callable

from polisi_scraper.adapters.base import BaseSiteAdapter
from polisi_scraper.adapters.dosm import DosmAdapter
from polisi_scraper.adapters.jpa import JpaAdapter
from polisi_scraper.adapters.moe import MoeAdapter
from polisi_scraper.adapters.mof import MofAdapter
from polisi_scraper.adapters.moh import MohAdapter

AdapterFactory = Callable[[], BaseSiteAdapter]


ADAPTER_REGISTRY: dict[str, AdapterFactory] = {
    "mof": MofAdapter,
    "moe": MoeAdapter,
    "jpa": JpaAdapter,
    "moh": MohAdapter,
    "dosm": DosmAdapter,
}


def get_adapter_registry() -> dict[str, AdapterFactory]:
    return ADAPTER_REGISTRY
