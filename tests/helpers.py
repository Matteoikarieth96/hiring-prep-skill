"""Shared test helpers: path setup and a fresh copy of the fictional guide."""
import copy
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
EXAMPLE = ROOT / "examples" / "fictional" / "guide.json"
TODAY = date(2026, 10, 8)

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

_GUIDE = json.loads(EXAMPLE.read_text(encoding="utf-8"))


def example_guide() -> dict:
    return copy.deepcopy(_GUIDE)
