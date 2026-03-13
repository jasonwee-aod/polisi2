"""Shared pytest fixtures for the polisi_scraper test suite."""

import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir():
    """Root fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture
def bheuu_fixtures():
    """BHEUU adapter test fixtures (JSON API responses)."""
    return FIXTURES_DIR / "bheuu"


@pytest.fixture
def dewan_johor_fixtures():
    """Dewan Johor adapter test fixtures (HTML pages, XML sitemaps)."""
    return FIXTURES_DIR / "dewan_johor"


@pytest.fixture
def dewan_selangor_fixtures():
    """Dewan Selangor adapter test fixtures (HTML pages, XML sitemaps)."""
    return FIXTURES_DIR / "dewan_selangor"


@pytest.fixture
def idfr_fixtures():
    """IDFR adapter test fixtures (HTML listing pages)."""
    return FIXTURES_DIR / "idfr"


@pytest.fixture
def kpkt_fixtures():
    """KPKT adapter test fixtures (HTML pages)."""
    return FIXTURES_DIR / "kpkt"


@pytest.fixture
def mcmc_fixtures():
    """MCMC adapter test fixtures (HTML pages)."""
    return FIXTURES_DIR / "mcmc"


@pytest.fixture
def moe_fixtures():
    """MOE adapter test fixtures."""
    return FIXTURES_DIR / "moe"


@pytest.fixture
def moh_fixtures():
    """MOH adapter test fixtures (HTML listing/detail pages)."""
    return FIXTURES_DIR / "moh"


@pytest.fixture
def mohe_fixtures():
    """MOHE adapter test fixtures."""
    return FIXTURES_DIR / "mohe"


@pytest.fixture
def perpaduan_fixtures():
    """Perpaduan adapter test fixtures."""
    return FIXTURES_DIR / "perpaduan"


@pytest.fixture
def rmp_fixtures():
    """RMP adapter test fixtures (HTML listing/detail pages)."""
    return FIXTURES_DIR / "rmp"
