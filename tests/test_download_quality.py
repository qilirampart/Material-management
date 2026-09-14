import unittest
from unittest.mock import patch

from src.vendor.douyin import DouyinDownloadService, DouyinResolutionRejected


class DownloadQualityTests(unittest.TestCase):
    def test_browser_dimension_below_filter_is_rejected_before_transfer(self):
        service = DouyinDownloadService()
        payload = {"media_url": "https://cdn.example/video.mp4", "width": 576, "height": 1024}

        with patch.object(service, "_resolve_share_url_via_browser", return_value=(payload, "browser://test")), \
             patch.object(service, "_download_file") as download_file:
            with self.assertRaises(DouyinResolutionRejected):
                service._download_via_browser_fallback(
                    "https://www.douyin.com/video/123", minimum_short_edge=720,
                )

        download_file.assert_not_called()
    def test_parser_candidates_prefer_highest_reported_bitrate(self):
        payload = {
            "bit_rate": [
                {
                    "bit_rate": 900_000,
                    "play_addr": {"url_list": ["https://cdn.example/video-low.mp4"]},
                },
                {
                    "bit_rate": 4_200_000,
                    "play_addr": {"url_list": ["https://cdn.example/video-high.mp4"]},
                },
            ]
        }

        urls = DouyinDownloadService()._extract_video_urls(payload)

        self.assertEqual(urls[0], "https://cdn.example/video-high.mp4")

    def test_resolution_hint_orders_candidates_when_bitrate_is_absent(self):
        payload = {
            "video_urls": [
                "https://cdn.example/play.mp4?ratio=720p",
                "https://cdn.example/play.mp4?ratio=1080p",
            ]
        }

        urls = DouyinDownloadService()._extract_video_urls(payload)

        self.assertIn("1080p", urls[0])


if __name__ == "__main__":
    unittest.main()
