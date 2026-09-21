import pathlib
import sys
import unittest
from unittest.mock import patch

_SRC_DIR = pathlib.Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from phantom_workstation.display import (
    ensure_compiled,
    get_display_status,
    get_source_path,
    resolve_display_ordinal,
    teleport_window,
)


class TestDisplay(unittest.TestCase):
    def test_compilation(self):
        source_path = get_source_path()
        self.assertIsNotNone(source_path)
        self.assertTrue(source_path.exists())
        compiled = ensure_compiled()
        self.assertTrue(compiled)

    def test_status_structure(self):
        st = get_display_status()
        self.assertIn("active", st)
        self.assertIn("status", st)

    def test_resolve_display_ordinal(self):
        # Display 1 is the primary display on macOS
        ord1 = resolve_display_ordinal(1)
        # In headless or CI without CoreGraphics display server, ord1 might be None, but on macOS desktop it returns 1
        if ord1 is not None:
            self.assertEqual(ord1, 1)

        # Unknown large display ID should resolve to None
        self.assertIsNone(resolve_display_ordinal(99999999))

    def test_teleport_window_injection_safety(self):
        # Malicious string with quotes and commands must not trigger AppleScript syntax error or injection
        with patch("phantom_workstation.display.get_display_status", return_value={"active": True, "origin_x": 100, "origin_y": 0}):
            res = teleport_window('Malicious"App; do shell script "touch /tmp/pwned"', 1)
            # Must safely return NO_PROCESS error, never executing injected script
            self.assertFalse(res["ok"])
            self.assertIn("Teleport failed", res["error"])
            self.assertFalse(pathlib.Path("/tmp/pwned").exists())


if __name__ == "__main__":
    unittest.main()
