import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.batch import run_batch
from src.task_input import links_to_rows


class ModeTests(unittest.TestCase):
    def test_share_text_and_duplicate_urls(self):
        rows = links_to_rows("分享 https://v.douyin.com/Abcd123/ 看视频\nhttps://v.douyin.com/Abcd123/\nhttps://www.douyin.com/video/123")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["video_id"], "123")

    def test_foreign_domain_rejected(self):
        with self.assertRaises(ValueError):
            links_to_rows("https://douyin.com.evil.test/video/123")

    def test_detection_only_never_downloads_missing_video(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.json"
            path.write_text(json.dumps(links_to_rows("https://www.douyin.com/video/123")), encoding="utf-8")
            with patch("src.batch.Downloader") as download, patch("src.batch.vision.load_profile", return_value={}), patch("src.batch.vision.fingerprint", return_value="test"):
                state = run_batch(path, Path(folder) / "out", {}, operation="detect")
            download.assert_not_called()
            self.assertEqual(state["records"]["123"]["status"], "review_required")
            self.assertIn("本地视频", state["records"]["123"]["reason"])
