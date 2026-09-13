import json
import tempfile
import unittest
from pathlib import Path
from queue import Queue
from unittest.mock import patch

from openpyxl import Workbook
from src.batch import _download_worker, download_concurrency_for, run_batch
from src.vision import classify


class DesktopWorkerTests(unittest.TestCase):
    def test_download_concurrency_is_limited_to_safe_browser_worker_count(self):
        self.assertEqual(download_concurrency_for({}, "download"), 1)
        self.assertEqual(download_concurrency_for({"download_concurrency": 2}, "download"), 2)
        self.assertEqual(download_concurrency_for({"download_concurrency": 99}, "both"), 3)
        self.assertEqual(download_concurrency_for({"download_concurrency": 3}, "detect"), 1)

    @patch("src.batch.Downloader")
    def test_parallel_download_worker_forwards_parse_and_transfer_events(self, downloader):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "video.mp4"
            events = Queue()

            def download(_url, output):
                downloader.return_value.on_event({"type": "progress", "stage": "解析视频链接"})
                downloader.return_value.on_event({
                    "type": "download_progress", "received": 512, "total": 1024,
                    "speed": 256, "percent": 50,
                })
                Path(output).write_bytes(b"video")
                return {"duration": 1}

            downloader.return_value.download.side_effect = download
            result = _download_worker(
                "https://www.douyin.com/video/1", str(target), {}, True, events,
                "1", 2, 3,
            )

            self.assertTrue(result["ok"])
            forwarded = [events.get_nowait(), events.get_nowait()]
            self.assertEqual(forwarded[0]["stage"], "解析视频链接")
            self.assertEqual(forwarded[1]["percent"], 50)
            self.assertTrue(all(event["video_id"] == "1" for event in forwarded))
            self.assertTrue(all(event["task_index"] == 2 for event in forwarded))

    def test_progress_events_report_position_in_selected_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            rows = [
                {
                    "video_id": str(index),
                    "url": f"https://www.douyin.com/video/{index}",
                    "input_error": "",
                    "local_path": str(folder / f"missing-{index}.mp4"),
                    "source": {},
                }
                for index in (101, 102, 103)
            ]
            input_path = folder / "input.json"
            input_path.write_text(json.dumps(rows), encoding="utf-8")
            events = []
            with patch("src.batch.vision.load_profile", return_value={}), \
                 patch("src.batch.vision.fingerprint", return_value="test"), \
                 patch("src.batch.export_report"):
                run_batch(
                    input_path,
                    folder / "output",
                    {},
                    operation="detect",
                    selected_ids=["101", "102", "103"],
                    on_event=events.append,
                )

            starts = [event for event in events if event.get("stage") == "准备处理"]
            self.assertEqual(
                [(event["task_index"], event["task_total"]) for event in starts],
                [(1, 3), (2, 3), (3, 3)],
            )

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
