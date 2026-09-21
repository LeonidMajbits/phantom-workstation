import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

_SRC_DIR = pathlib.Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from phantom_workstation.workstation import PhantomWorkstation


class TestWorkstation(unittest.TestCase):
    def test_dry_run_loop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_runs = pathlib.Path(tmpdir) / "runs"
            station = PhantomWorkstation(
                objective="Test dry run loop",
                max_steps=2,
                dry_run=True,
                runs_dir=tmp_runs,
            )
            res = station.run_loop()
            self.assertEqual(res["status"], "COMPLETED")
            self.assertEqual(res["steps_completed"], 2)
            self.assertTrue(pathlib.Path(res["report_path"]).exists())
            self.assertGreater(res["tokens"]["total_full_tree"], 0)

    def test_microsecond_unique_run_ids(self):
        station1 = PhantomWorkstation(objective="Run 1", dry_run=True)
        station2 = PhantomWorkstation(objective="Run 2", dry_run=True)
        self.assertNotEqual(station1.run_id, station2.run_id)

    @patch("phantom_workstation.workstation.PhantomWorkstation.initialize_display", return_value=True)
    @patch("phantom_workstation.workstation.capture_display", return_value={"ok": False, "error": "Display disconnected"})
    def test_degraded_status_on_capture_failure(self, mock_capture, mock_init):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_runs = pathlib.Path(tmpdir) / "runs"
            station = PhantomWorkstation(
                objective="Test failure tracking",
                max_steps=2,
                dry_run=False,
                runs_dir=tmp_runs,
            )
            res = station.run_loop()
            self.assertFalse(res["ok"])
            self.assertEqual(res["status"], "DEGRADED")
            self.assertEqual(len(res["failed_captures"]), 2)


if __name__ == "__main__":
    unittest.main()
