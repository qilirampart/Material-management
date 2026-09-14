import unittest
from pathlib import Path


class OnlineInstallerTests(unittest.TestCase):
    def test_online_installer_uses_inno_download_with_fixed_release_asset(self):
        text = Path('online_installer.iss').read_text(encoding='utf-8-sig')
        self.assertIn('DownloadTemporaryFile', text)
        self.assertIn('DianzhongMaterialAssistant-Setup-{#AppVersion}.exe', text)
        self.assertIn('SetupIconFile=assets\\icons\\app-icon.ico', text)
