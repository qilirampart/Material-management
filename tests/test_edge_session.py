import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.edge_session import build_edge_command, open_persistent_edge, persistent_edge_profile


class EdgeSessionTests(unittest.TestCase):
    def test_profile_defaults_to_project_runtime(self):
        self.assertEqual(persistent_edge_profile({}).name, "edge-cdp-profile")

    @patch("src.edge_session.find_edge", return_value=Path("C:/Edge/msedge.exe"))
    def test_command_uses_dedicated_profile_and_debug_port(self, _find):
        command = build_edge_command(
            "https://market.wuread.cn/market-admin/", Path("C:/session"), 9333
        )
        self.assertIn("--remote-debugging-port=9333", command)
        self.assertIn("--user-data-dir=C:\\session", command)
        self.assertEqual(command[-1], "https://market.wuread.cn/market-admin/")

    def test_rejects_credential_bearing_url(self):
        with self.assertRaises(ValueError):
            build_edge_command("https://name:password@example.com", Path("C:/session"))

    @patch("src.edge_session.subprocess.Popen")
    @patch("src.edge_session.find_edge", return_value=Path("C:/Edge/msedge.exe"))
    def test_launcher_creates_and_reuses_configured_profile(self, _find, popen):
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / "edge"
            result = open_persistent_edge(
                "https://market.wuread.cn/market-admin/",
                {"edge_profile_path": str(profile)},
            )
        self.assertEqual(result, profile.resolve())
        popen.assert_called_once()
        self.assertIs(popen.call_args.kwargs["stdout"], subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()
