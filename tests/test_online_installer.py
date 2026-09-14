import unittest
from pathlib import Path


class OnlineInstallerTests(unittest.TestCase):
    def test_online_installer_uses_inno_download_with_fixed_release_asset(self):
        text = Path('online_installer.iss').read_text(encoding='utf-8-sig')
        self.assertIn('DownloadTemporaryFile', text)
        self.assertIn('DianzhongMaterialAssistant-Setup-{#AppVersion}.exe', text)
        self.assertIn('SetupIconFile=assets\\icons\\app-icon.ico', text)
        self.assertIn('IntToStr(Progress div 1048576)', text)
        self.assertNotIn('%.1f', text)

    def test_macos_online_installer_is_a_native_app_with_download_progress(self):
        source = Path('scripts/macos_online_installer.swift').read_text(encoding='utf-8')
        build = Path('scripts/build_macos_online_installer.py').read_text(encoding='utf-8')
        self.assertIn('URLSessionDownloadDelegate', source)
        self.assertIn('activateFileViewerSelecting', source)
        self.assertIn('iconutil', build)
