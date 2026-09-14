import json
import tempfile
import unittest
from pathlib import Path

from src.paths import _migrate_legacy_settings


class UserDataPathTests(unittest.TestCase):
    def test_migration_copies_settings_but_not_cached_browser_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            legacy, target = root / 'legacy', root / 'user-data'
            legacy.mkdir()
            (legacy / 'model_profiles.json').write_text('{"llm": {}}', encoding='utf-8')
            (legacy / 'desktop_config.json').write_text(json.dumps({
                'model_config_path': str(legacy / 'model_profiles.json'),
            }), encoding='utf-8')
            (legacy / 'edge-cdp-profile').mkdir()
            _migrate_legacy_settings(legacy, target)
            self.assertTrue((target / 'model_profiles.json').is_file())
            self.assertFalse((target / 'edge-cdp-profile').exists())
            migrated = json.loads((target / 'desktop_config.json').read_text(encoding='utf-8'))
            self.assertEqual(migrated['model_config_path'], str(target / 'model_profiles.json'))
