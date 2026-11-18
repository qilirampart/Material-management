"""The installed runtime must be replaced, not merged with obsolete dependencies."""
from pathlib import Path
import unittest


class WindowsUpgradeInstallerTests(unittest.TestCase):
    def test_upgrade_replaces_only_bundled_internal_runtime(self):
        script=Path('installer.iss').read_text(encoding='utf-8-sig')
        self.assertIn('[InstallDelete]',script)
        section=script.split('[InstallDelete]',1)[1].split('[',1)[0]
        entries=[line.strip() for line in section.splitlines() if line.strip() and not line.startswith(';')]
        self.assertEqual(entries,['Type: filesandordirs; Name: "{app}\\_internal"'])
        self.assertLess(script.index('[InstallDelete]'),script.index('[Files]'))

    def test_ci_checks_cover_install_and_user_data_preservation(self):
        workflow=Path('.github/workflows/desktop-release.yml').read_text(encoding='utf-8')
        self.assertIn('verify_windows_upgrade.py',workflow)
        script=Path('scripts/verify_windows_upgrade.py').read_text(encoding='utf-8')
        self.assertIn('obsolete-runtime-file.pyd',script)
        self.assertIn('numpy',script)
        self.assertIn('preserved_user_files',script)
        self.assertIn('--smoke-ui',script)

    def test_upgrade_test_installer_never_creates_user_shortcuts_or_registry_entry(self):
        script=Path('installer.iss').read_text(encoding='utf-8-sig')
        self.assertIn('#ifdef UpgradeTestBuild\n',script)
        self.assertIn('CreateUninstallRegKey=no',script)
        self.assertIn('Uninstallable=no',script)
        self.assertIn('#ifndef UpgradeTestBuild\n[Icons]',script)
