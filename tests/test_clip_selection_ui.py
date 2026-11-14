import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication,QWidget
from shiboken6 import delete
from src.micro_settings import MicroSettings
from src.micro_presets import RECOMMENDED,validate_settings,read_presets


class ClipSelectionUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):self.host=QWidget()
    def tearDown(self):self.host.close();delete(self.host);self.app.processEvents()

    def test_switching_modes_disables_only_inactive_controls_without_resetting_values(self):
        panel=MicroSettings();panel.setParent(self.host)
        panel.fields['range_start'].setValue(12);panel.fields['range_duration'].setValue(8)
        self.assertFalse(panel.fields['range_start'].parentWidget().isEnabled())
        panel.fields['clip_mode'].setCurrentIndex(1)
        self.assertTrue(panel.fields['range_start'].parentWidget().isEnabled())
        self.assertFalse(panel.trim_start.parentWidget().isEnabled())
        self.assertTrue(panel.speed.parentWidget().isEnabled())
        panel.fields['clip_mode'].setCurrentIndex(0)
        self.assertTrue(panel.trim_start.parentWidget().isEnabled())
        self.assertEqual(panel.values()['range_start'],12);self.assertEqual(panel.values()['range_duration'],8)

    def test_favorites_and_older_settings_preserve_original_time_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'favorites.json';panel=MicroSettings(presets_path=path);panel.setParent(self.host)
            values=dict(RECOMMENDED,clip_mode='range',range_start=20,range_duration=15,trim_start=2,trim_end=3)
            panel.apply_settings(values);self.assertEqual(panel.values(),values)
            with patch('src.micro_settings.QInputDialog.getText',return_value=('保留中段',True)):panel.save_favorite()
            other=MicroSettings(presets_path=path);other.setParent(self.host)
            other.apply_settings(read_presets(path)['保留中段']);self.assertEqual(other.values(),values)
            old={k:v for k,v in RECOMMENDED.items() if k not in {'clip_mode','range_start','range_duration'}}
            self.assertEqual(validate_settings(old)['clip_mode'],'trim')
