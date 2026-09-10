import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.vendor.douyin import DouyinDownloadService


class BrowserProbeReuseTests(unittest.TestCase):
    def test_browser_probe_runs_in_worker_process_and_can_be_reused(self):
        result = SimpleNamespace(
            page_url="https://www.douyin.com/video/123",
            media_url="https://cdn.example/video.mp4",
            audio_url="https://cdn.example/audio.m4a",
            title="sample",
            source="network",
        )
        service = DouyinDownloadService()

        with patch(
            "src.vendor.browser_probe.probe_douyin_video_url",
            return_value=result,
        ) as probe:
            first, first_source = service._resolve_share_url_via_browser(
                "https://www.douyin.com/video/123"
            )
            second, second_source = service._resolve_share_url_via_browser(
                "https://www.douyin.com/video/456"
            )

        self.assertEqual(probe.call_count, 2)
        self.assertEqual(probe.call_args.kwargs["timeout_ms"], 60_000)
        self.assertEqual(first["media_url"], result.media_url)
        self.assertEqual(second["audio_url"], result.audio_url)
        self.assertEqual(first_source, "browser://douyin-current-src")
        self.assertEqual(second_source, "browser://douyin-current-src")


if __name__ == "__main__":
    unittest.main()
