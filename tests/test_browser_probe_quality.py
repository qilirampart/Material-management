import unittest

from src.vendor.browser_probe import looks_like_media_url, media_url_quality_score


class BrowserProbeQualityTests(unittest.TestCase):
    def test_full_aweme_play_url_is_a_video_candidate(self):
        url = (
            "https://www.douyin.com/aweme/v1/play/"
            "?video_id=abc&is_play_url=1&target=123&downgrade_264=1"
        )

        self.assertTrue(looks_like_media_url(url))

    def test_full_play_url_outranks_low_bitrate_adaptive_stream(self):
        full = (
            "https://www.douyin.com/aweme/v1/play/"
            "?video_id=abc&is_play_url=1&target=123&downgrade_264=1"
        )
        adaptive = "https://v11-weba.douyinvod.com/video?mime_type=video_mp4&br=397"

        self.assertGreater(media_url_quality_score(full), media_url_quality_score(adaptive))


if __name__ == "__main__":
    unittest.main()
