import unittest

from src.vendor.douyin import DouyinDownloadService


class DownloadQualityTests(unittest.TestCase):
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
