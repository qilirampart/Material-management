"""The installed runtime must be replaced, not merged with obsolete dependencies."""
from pathlib import Path
import tempfile
import unittest


class WindowsUpgradeInstallerTests(unittest.TestCase):
    def test_upgrade_check_accepts_new_numpy_but_rejects_exact_old_file(self):
        from scripts.verify_windows_upgrade import assert_obsolete_runtime_removed, OBSOLETE_RUNTIME_FILES
        with tempfile.TemporaryDirectory() as location:
            internal=Path(location)
            fresh=internal/'numpy/_core/new_numpy.pyd'
            fresh.parent.mkdir(parents=True)
            fresh.write_bytes(b'new')
            assert_obsolete_runtime_removed(internal)
            for name in OBSOLETE_RUNTIME_FILES:
                legacy=internal/name
                legacy.parent.mkdir(parents=True,exist_ok=True)
                legacy.write_bytes(b'old')
                with self.assertRaises(RuntimeError):
                    assert_obsolete_runtime_removed(internal)
                legacy.unlink()
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
