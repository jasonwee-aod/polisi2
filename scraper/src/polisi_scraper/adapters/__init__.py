"""Adapter registry and discovery utilities."""

from __future__ import annotations

from typing import Callable

from polisi_scraper.adapters.base import BaseSiteAdapter

AdapterFactory = Callable[[], BaseSiteAdapter]


def get_adapter_registry() -> dict[str, AdapterFactory]:
    """Return slug -> adapter factory.

    Concrete adapters are registered in Plan 01-03.
    """
    return {}
