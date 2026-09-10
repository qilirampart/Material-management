import unittest
from unittest.mock import Mock

import requests

from src.vendor.douyin import DouyinDownloadError, DouyinDownloadService
from src.vendor.failover import FailoverRouter


class ParserFailoverTests(unittest.TestCase):
    def test_all_open_providers_stay_skipped_during_cooldown(self):
        provider = {"name": "only", "priority": 1}
        router = FailoverRouter("test")
        router.record_failure(
            provider,
            "offline",
            failure_threshold=1,
            cooldown_seconds=300,
        )

        self.assertEqual(
            router.ordered_candidates(
                [provider],
                failure_threshold=1,
                cooldown_seconds=300,
            ),
            [],
        )

    def test_connection_failure_opens_provider_circuit_immediately(self):
        provider = {"name": "only", "base_url": "https://parser.example/api"}
        service = DouyinDownloadService()
        service._config = {"enabled": True}
        service._api_config_service.data = {
            "douyin_parser": {
                "providers": [provider],
                "failover": {"failure_threshold": 2, "cooldown_seconds": 300},
            }
        }
        service._resolve_share_url_locally = Mock(side_effect=DouyinDownloadError("local failed"))
        service._resolve_share_url_via_service = Mock(side_effect=requests.ConnectionError("offline"))
        service._failover_router.record_failure = Mock()

        with self.assertRaises(DouyinDownloadError):
            service._resolve_share_url("https://www.douyin.com/video/123")

        self.assertEqual(
            service._failover_router.record_failure.call_args.kwargs["failure_threshold"],
            1,
        )

    def test_parser_service_uses_short_connection_timeout(self):
        service = DouyinDownloadService()
        service._config = {
            "timeout_seconds": 45,
            "parser_connect_timeout_seconds": 5,
        }
        response = Mock()
        response.text = '{"video_url":"https://cdn.example/video.mp4"}'
        response.raise_for_status.return_value = None
        session = Mock()
        session.get.return_value = response
        service._session = Mock(return_value=session)

        service._resolve_share_url_via_service(
            "https://www.douyin.com/video/123",
            provider={"base_url": "https://parser.example/api"},
        )

        self.assertEqual(session.get.call_args.kwargs["timeout"], (5.0, 45.0))


if __name__ == "__main__":
    unittest.main()
