"""Add src/ to sys.path so pytest can import idfr_scraper without installing."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
