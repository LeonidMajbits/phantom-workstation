"""Unit tests for phantom_workstation."""

import pathlib
import sys

_SRC_DIR = pathlib.Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

