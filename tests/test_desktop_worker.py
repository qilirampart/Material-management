import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook
from src.batch import run_batch
from src.vision import classify


class DesktopWorkerTests(unittest.TestCase):
    def test_pause_preserves_unstarted_records_and_emits_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            workbook = Workbook()
            workbook.active.append(["剧名", "视频ID", "热度", "点赞数", "创建时间", "原始链接"])
            workbook.active.append(["样本", "123", 1, 1, "", "https://www.douyin.com/video/123"])
            path = folder / "input.xlsx"
            workbook.save(path)
            events = []
            with patch("src.batch.Downloader") as downloader:
                state = run_batch(path, folder / "output", {}, download_only=True,
                                  should_stop=lambda: True, on_event=events.append)
                self.assertEqual(state["records"], {})
                downloader.return_value.download.assert_not_called()
                self.assertEqual(events[-1]["type"], "paused")

    def test_custom_phrase_is_used(self):
        frames = [{"index": i, "text": "点击下方链接", "logo": "absent", "logo_evidence": "", "uncertain": False} for i in (1, 2, 3)]
        self.assertEqual(classify({"frames": frames}, phrases=["点击下方链接"])["status"], "blocked")
