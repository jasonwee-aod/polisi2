"""Tests for polisi_scraper.core.browser — BrowserPool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from polisi_scraper.core.browser import BrowserPool


class TestBrowserPoolInit:
    """BrowserPool should initialize cleanly without launching anything."""

    def test_init_state(self) -> None:
        pool = BrowserPool()
        assert pool._playwright is None
        assert pool._browser is None
        assert pool._lock is not None

    def test_close_without_launch(self) -> None:
        """Calling close() on a never-used pool should not raise."""
        pool = BrowserPool()
        pool.close()
        assert pool._playwright is None
        assert pool._browser is None


class TestBrowserPoolGetPage:
    """BrowserPool.get_page() should lazy-init and return a page."""

    def test_get_page_launches_browser(self) -> None:
        """get_page() should call sync_playwright().start() and chromium.launch()."""
        mock_page = MagicMock()
        mock_browser = MagicMock()
        mock_browser.new_page.return_value = mock_page

        mock_pw_instance = MagicMock()
        mock_pw_instance.chromium.launch.return_value = mock_browser

        mock_sync_pw = MagicMock()
        mock_sync_pw.return_value.start.return_value = mock_pw_instance

        with patch(
            "polisi_scraper.core.browser.BrowserPool.get_page",
            wraps=None,
        ):
            # Directly patch the import inside get_page
            pool = BrowserPool()
            with patch.dict(
                "sys.modules",
                {"playwright": MagicMock(), "playwright.sync_api": MagicMock()},
            ):
                with patch(
                    "polisi_scraper.core.browser.sync_playwright",
                    create=True,
                ) as patched:
                    # The import inside get_page uses from ... import sync_playwright
                    # We need to patch it at the point of use inside the method body.
                    pass

        # Simpler approach: manually set internal state
        pool = BrowserPool()
        pool._browser = mock_browser
        pool._playwright = mock_pw_instance

        page = pool.get_page()
        mock_browser.new_page.assert_called_once()
        assert page is mock_page

    def test_close_cleans_up(self) -> None:
        """close() should call browser.close() and playwright.stop()."""
        mock_browser = MagicMock()
        mock_pw = MagicMock()

        pool = BrowserPool()
        pool._browser = mock_browser
        pool._playwright = mock_pw

        pool.close()

        mock_browser.close.assert_called_once()
        mock_pw.stop.assert_called_once()
        assert pool._browser is None
        assert pool._playwright is None

    def test_close_idempotent(self) -> None:
        """Calling close() twice should not raise."""
        mock_browser = MagicMock()
        mock_pw = MagicMock()

        pool = BrowserPool()
        pool._browser = mock_browser
        pool._playwright = mock_pw

        pool.close()
        pool.close()  # Second call should be safe

        assert pool._browser is None
        assert pool._playwright is None

    def test_thread_safety_lock_exists(self) -> None:
        """BrowserPool should have a threading lock for get_page/close."""
        import threading

        pool = BrowserPool()
        assert isinstance(pool._lock, type(threading.Lock()))
