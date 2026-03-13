from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from polisi_scraper.adapters import get_adapter_registry
from polisi_scraper.adapters.base import BaseSiteAdapter


EXPECTED_ADAPTERS = {
    "bheuu", "dewan_johor", "dewan_selangor", "idfr", "kpkt",
    "mcmc", "moe", "moh", "mohe", "perpaduan", "rmp",
}


def test_adapter_registry_has_eleven_sites() -> None:
    registry = get_adapter_registry()
    assert set(registry.keys()) == EXPECTED_ADAPTERS


def test_adapter_smoke_matrix() -> None:
    registry = get_adapter_registry()

    for slug, cls in registry.items():
        adapter = cls()
        assert isinstance(adapter, BaseSiteAdapter)
        assert adapter.slug == slug
        assert adapter.agency
        assert hasattr(adapter, "discover")
        assert hasattr(adapter, "fetch_and_extract")
        assert hasattr(adapter, "extract_downloads")
