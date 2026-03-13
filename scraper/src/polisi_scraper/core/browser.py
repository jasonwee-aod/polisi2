"""Lazy-initialized Playwright browser pool shared across adapters."""

from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)


class BrowserPool:
    """Manages a single headless Chromium instance, lazy-initialized on first use."""

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._lock = threading.Lock()

    def get_page(self):
        """Get a new Playwright page. Launches browser on first call."""
        with self._lock:
            if self._browser is None:
                try:
                    from playwright.sync_api import sync_playwright
                    self._playwright = sync_playwright().start()
                    self._browser = self._playwright.chromium.launch(headless=True)
                    log.info("Playwright browser launched")
                except Exception:
                    log.warning("Playwright not available; browser features disabled")
                    raise
            return self._browser.new_page()

    def close(self) -> None:
        with self._lock:
            if self._browser:
                try:
                    self._browser.close()
                except Exception:
                    pass
                self._browser = None
            if self._playwright:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
                log.info("Playwright browser pool closed")
