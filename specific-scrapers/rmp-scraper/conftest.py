# Root conftest.py — adds src/ to sys.path so pytest finds the package
# without requiring an editable install. Works on Python 3.9+.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
