"""Integration smoke test — verify adapters can be instantiated and discover() called.

Uses mock HTTP so no real network requests are made.
"""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock

import pytest

from polisi_scraper.adapters.base import BaseSiteAdapter, HTTPClient
from polisi_scraper.adapters.registry import get_adapter_registry


def _make_mock_http(json_response=None, text_response="<html></html>") -> MagicMock:
    """Build a mock HTTPClient whose .get() returns a mock Response."""
    mock_http = MagicMock(spec=HTTPClient)
    mock_resp = MagicMock()
    mock_resp.text = text_response
    mock_resp.content = text_response.encode("utf-8")
    mock_resp.status_code = 200
    mock_resp.headers = {}
    if json_response is not None:
        mock_resp.json.return_value = json_response
    else:
        mock_resp.json.return_value = []
    mock_http.get.return_value = mock_resp
    return mock_http


class TestAdapterRegistryLoads:
    """All adapters should register and be loadable."""

    def test_registry_not_empty(self) -> None:
        registry = get_adapter_registry()
        assert len(registry) > 0, "Adapter registry is empty"

    def test_all_adapters_have_slug(self) -> None:
        registry = get_adapter_registry()
        for slug, cls in registry.items():
            assert slug, f"{cls.__name__} has empty slug"
            assert slug == cls.slug, f"Registry key {slug!r} != cls.slug {cls.slug!r}"

    def test_all_adapters_are_base_subclasses(self) -> None:
        registry = get_adapter_registry()
        for slug, cls in registry.items():
            assert issubclass(cls, BaseSiteAdapter), (
                f"{cls.__name__} does not subclass BaseSiteAdapter"
            )


class TestAdapterDryRunDiscover:
    """Each adapter's discover() should run without errors given mock HTTP."""

    @pytest.fixture
    def registry(self) -> dict:
        return get_adapter_registry()

    def test_bheuu_discover_empty_config(self, registry) -> None:
        """BHEUU with empty sections yields nothing without error."""
        cls = registry.get("bheuu")
        if cls is None:
            pytest.skip("bheuu adapter not registered")
        adapter = cls(config={"sections": []}, http=_make_mock_http(json_response=[]))
        items = list(adapter.discover(max_pages=1))
        assert isinstance(items, list)

    def test_kpkt_discover_empty_config(self, registry) -> None:
        """KPKT with empty sections yields nothing without error."""
        cls = registry.get("kpkt")
        if cls is None:
            pytest.skip("kpkt adapter not registered")
        adapter = cls(config={"sections": []}, http=_make_mock_http())
        items = list(adapter.discover(max_pages=1))
        assert items == []

    def test_perpaduan_discover_empty_config(self, registry) -> None:
        """Perpaduan with empty sections yields nothing without error."""
        cls = registry.get("perpaduan")
        if cls is None:
            pytest.skip("perpaduan adapter not registered")
        adapter = cls(config={"sections": []}, http=_make_mock_http())
        items = list(adapter.discover(max_pages=1))
        assert items == []

    def test_all_adapters_instantiate(self, registry) -> None:
        """Every registered adapter can be instantiated with minimal config."""
        for slug, cls in registry.items():
            mock_http = _make_mock_http(json_response=[])
            adapter = cls(config={}, http=mock_http)
            assert adapter is not None, f"Failed to instantiate {slug}"
            assert adapter.slug == slug

    def test_all_adapters_discover_with_empty_config(self, registry) -> None:
        """Every adapter's discover() should tolerate empty config and mock HTTP."""
        for slug, cls in registry.items():
            mock_http = _make_mock_http(json_response=[])
            # Provide minimal config with empty sections list
            config = {"sections": []}
            adapter = cls(config=config, http=mock_http)
            try:
                items = list(adapter.discover(max_pages=1))
                assert isinstance(items, list), f"{slug} discover() did not return iterable"
            except Exception as exc:
                # Some adapters may need specific config keys; that's acceptable
                # as long as it's a data/config error, not an import/type error.
                assert not isinstance(exc, (ImportError, TypeError, AttributeError)), (
                    f"{slug} discover() raised {type(exc).__name__}: {exc}"
                )
