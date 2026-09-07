import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import QApplication

from src.browser_session import configure_persistent_profile, platform_browser_root


class BrowserSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_default_session_is_outside_program_runtime(self):
        self.assertEqual(platform_browser_root({}).name, "browser")
        self.assertIn("Dianzhong", str(platform_browser_root({})))

    def test_profile_forces_cookie_and_permission_persistence(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = QWebEngineProfile("session-test", self.app)
            configure_persistent_profile(profile, Path(folder))

            self.assertEqual(
                profile.persistentCookiesPolicy(),
                QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies,
            )
            self.assertEqual(
                profile.persistentPermissionsPolicy(),
                QWebEngineProfile.PersistentPermissionsPolicy.StoreOnDisk,
            )
            self.assertEqual(Path(profile.persistentStoragePath()), Path(folder) / "storage")
            profile.deleteLater()


if __name__ == "__main__":
    unittest.main()
