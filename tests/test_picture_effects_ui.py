import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication,QWidget,QDialog
from shiboken6 import delete
from src.picture_effects_dialog import PictureEffectsDialog
from src.picture_effects import PICTURE_DEFAULTS
from src.micro_settings import MicroSettings
from src.micro_presets import RECOMMENDED,validate_settings,read_presets


class PictureEffectsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):self.host=QWidget()
    def tearDown(self):self.host.close();delete(self.host);self.app.processEvents()

    def test_edit_copy_save_reset_and_invalid_color(self):
        original=dict(PICTURE_DEFAULTS);d=PictureEffectsDialog(original,self.host)
        self.assertFalse(d.fit.isEnabled())
        d.layout_choice.setCurrentIndex(d.layout_choice.findData('quad'))
        self.assertTrue(d.fit.isEnabled())
        d.style.setCurrentIndex(d.style.findData('sepia'));d.width.setValue(12)
        d.color.setText('no');d.save();self.assertNotEqual(d.result(),QDialog.DialogCode.Accepted)
        d.color.setText('FFCC00');d.vignette.setValue(35);d.save()
        self.assertEqual(d.settings['grid_layout'],'quad');self.assertEqual(d.settings['vignette'],.35)
        self.assertEqual(original,PICTURE_DEFAULTS)
        other=PictureEffectsDialog(d.settings,self.host);other.reset();other.save()
        self.assertEqual(other.settings,PICTURE_DEFAULTS)

    def test_favorite_and_legacy_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'favorites.json';panel=MicroSettings(presets_path=path);panel.setParent(self.host)
            panel.picture_effects=dict(PICTURE_DEFAULTS,grid_layout='three_rows',picture_style='monochrome',border_width=8)
            with patch('src.micro_settings.QInputDialog.getText',return_value=('三分屏黑白',True)):panel.save_favorite()
            other=MicroSettings(presets_path=path);other.setParent(self.host)
            other.apply_settings(read_presets(path)['三分屏黑白'])
            self.assertEqual(other.values(),panel.values())
            old={k:v for k,v in RECOMMENDED.items() if k not in PICTURE_DEFAULTS}
            migrated=validate_settings(old)
            self.assertEqual({k:migrated[k] for k in PICTURE_DEFAULTS},PICTURE_DEFAULTS)
