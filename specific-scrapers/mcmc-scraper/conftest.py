"""
Root conftest.py – adds src/ to sys.path so that mcmc_scraper is importable
without a full `pip install -e .` when running on Python 3.9 (system Python).

This mimics the pattern used in the other scrapers in this project.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
