"""
Add src/ to sys.path so pytest can import moh_scraper without installing the
package. This mirrors the pattern used across all scrapers in this repo.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
