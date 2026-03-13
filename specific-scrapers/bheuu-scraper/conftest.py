"""
Add src/ to sys.path so tests can import bheuu_scraper without installation.
Works on Python 3.9 (system Python) before editable install is available.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
