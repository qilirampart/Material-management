import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWebEngineCore import QWebEngineProfile

from src.browser_session import configure_persistent_profile, platform_browser_root, shared_platform_profile


class BrowserSessionTests(unittest.TestCase):
    def test_two_workflows_share_one_profile_not_two_storage_owners(self):
        owner = MagicMock()
        owner._material_platform_profiles = {}
        with tempfile.TemporaryDirectory() as folder, patch('src.browser_session.QWebEngineProfile') as factory:
            config = {'platform_browser_data_path': folder}
            one = shared_platform_profile(config, owner=owner)
            two = shared_platform_profile(config, owner=owner)
            self.assertIs(one, two)
            factory.assert_called_once()

    def test_default_session_is_outside_program_runtime(self):
        from src.paths import USER_DATA_ROOT, DEFAULT_USER_DATA_ROOT
        self.assertEqual(platform_browser_root({}), USER_DATA_ROOT / 'browser')
        self.assertIn('Dianzhong', str(DEFAULT_USER_DATA_ROOT))

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
