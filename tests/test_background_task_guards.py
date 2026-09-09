import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from src.desktop import MainWindow


class RunningTask:
    def isRunning(self):
        return True


class BackgroundTaskGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow(restore=False)

    def tearDown(self):
        self.window.bitrate_task = None
        self.window.quality_task = None
        self.window.platform.staging_task = None
        self.window.close()
        self.window.deleteLater()

    def test_new_batch_keeps_current_state_while_bitrate_task_runs(self):
        self.window.rows = [{"video_id": "123"}]
        self.window.records = {"123": {"download": "已下载"}}
        self.window.bitrate_task = RunningTask()

        self.window.new_batch()

        self.assertEqual(self.window.rows, [{"video_id": "123"}])
        self.assertIn("123", self.window.records)

    def test_platform_background_work_also_blocks_batch_reset(self):
        self.window.rows = [{"video_id": "123"}]
        self.window.platform.staging_task = RunningTask()

        self.window.new_batch()

        self.assertEqual(self.window.rows, [{"video_id": "123"}])

    def test_history_batch_cannot_replace_state_during_background_work(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "results.json").write_text(json.dumps({
                "input_rows": [{"video_id": "new"}],
                "records": {"new": {}},
            }), encoding="utf-8")
            self.window.rows = [{"video_id": "current"}]
            self.window.bitrate_task = RunningTask()

            with patch("src.desktop.QMessageBox.warning"):
                self.window.open_batch(root)

            self.assertEqual(self.window.rows, [{"video_id": "current"}])

    def test_start_batch_is_blocked_while_quality_task_runs(self):
        self.window.quality_task = RunningTask()

        with patch("src.desktop.QMessageBox.information") as information:
            self.window.start_batch()

        self.assertIsNone(self.window.process)
        information.assert_not_called()

    def test_close_is_ignored_while_background_task_runs(self):
        self.window.bitrate_task = RunningTask()
        event = QCloseEvent()

        self.window.closeEvent(event)

        self.assertFalse(event.isAccepted())
        self.assertIn("后台", self.window.statusBar().currentMessage())


if __name__ == "__main__":
    unittest.main()
