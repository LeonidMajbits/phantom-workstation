import os
import pathlib
import sys
import unittest
from unittest.mock import patch

_SRC_DIR = pathlib.Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from phantom_workstation.display import (
    BIN_PATH,
    capture_display,
    ensure_compiled,
    get_display_status,
    get_source_path,
    resolve_display_ordinal,
    start_display,
    stop_display,
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

    @patch("phantom_workstation.display.get_display_status")
    @patch("phantom_workstation.display.resolve_display_ordinal", return_value=None)
    @patch("subprocess.run")
    def test_capture_display_fails_closed_when_ordinal_unresolved(self, mock_subproc, mock_resolve, mock_status):
        # When display is active with a CG display ID, but no ordinal can be resolved:
        # It must FAIL CLOSED immediately, never capturing display 1 and never calling screencapture.
        mock_status.return_value = {"active": True, "display_id": 8888}
        res = capture_display(pathlib.Path("/tmp/test_should_not_exist.png"))
        self.assertFalse(res["ok"])
        self.assertIn("Could not resolve 1-based display ordinal for CG display ID 8888", res["error"])
        self.assertEqual(res["display_id"], 8888)
        mock_subproc.assert_not_called()

    @patch("shutil.which", return_value=None)
    @patch("phantom_workstation.display.BIN_PATH")
    def test_ensure_compiled_handles_missing_clang_gracefully(self, mock_bin, mock_which):
        # If clang executable is absent, ensure_compiled must return False without unhandled FileNotFoundError
        mock_bin.exists.return_value = False
        self.assertFalse(ensure_compiled())

    def test_native_source_synchronization(self):
        # Verifies that repo root c_src and package-bundled src/phantom_workstation/c_src remain byte-for-byte identical
        pkg_root = pathlib.Path(__file__).resolve().parent.parent
        root_src = pkg_root / "c_src" / "phantom_display.m"
        pkg_src = pkg_root / "src" / "phantom_workstation" / "c_src" / "phantom_display.m"
        self.assertTrue(root_src.exists(), f"Missing root source at {root_src}")
        self.assertTrue(pkg_src.exists(), f"Missing package source at {pkg_src}")
        self.assertEqual(
            root_src.read_bytes(),
            pkg_src.read_bytes(),
            "Source drift detected: c_src/phantom_display.m differs from src/phantom_workstation/c_src/phantom_display.m",
        )

    @unittest.skipUnless(os.environ.get("PHANTOM_INTEGRATION_TESTS"), "Opt-in integration test requiring active macOS WindowServer")
    def test_display_lifecycle_live_integration(self):
        # End-to-end integration test: start virtual display, resolve ordinal, capture frame, teardown
        start_res = start_display(1280, 720)
        try:
            self.assertTrue(start_res.get("ok"))
            st = get_display_status()
            self.assertTrue(st.get("active"))
            did = st.get("display_id")
            self.assertIsNotNone(did)
            ordinal = resolve_display_ordinal(int(did))
            self.assertIsNotNone(ordinal)

            cap_res = capture_display()
            self.assertTrue(cap_res.get("ok"))
            self.assertTrue(pathlib.Path(cap_res["path"]).exists())
            self.assertGreater(cap_res["size_bytes"], 0)
        finally:
            stop_display()


if __name__ == "__main__":
    unittest.main()
