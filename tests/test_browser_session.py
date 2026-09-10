import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWebEngineCore import QWebEngineProfile

from src.browser_session import configure_persistent_profile, platform_browser_root


class BrowserSessionTests(unittest.TestCase):
    def test_default_session_is_outside_program_runtime(self):
        self.assertEqual(platform_browser_root({}).name, "browser")
        self.assertIn("Dianzhong", str(platform_browser_root({})))

    def test_profile_forces_cookie_and_permission_persistence(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = MagicMock()
            configure_persistent_profile(profile, Path(folder))

            profile.setPersistentCookiesPolicy.assert_called_once_with(
                QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies,
            )
            profile.setPersistentPermissionsPolicy.assert_called_once_with(
                QWebEngineProfile.PersistentPermissionsPolicy.StoreOnDisk,
            )
            profile.setPersistentStoragePath.assert_called_once_with(
                str(Path(folder).resolve() / "storage")
            )
            profile.setCachePath.assert_called_once_with(
                str(Path(folder).resolve() / "cache")
            )


if __name__ == "__main__":
    unittest.main()
