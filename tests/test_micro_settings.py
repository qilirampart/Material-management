import os
import unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from src.micro_settings import MicroSettings
from src.material_variants import VariantOptions


class MicroSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_all_six_categories_have_valid_defaults_and_map_values(self):
        panel=MicroSettings()
        self.assertEqual(panel.tabs.count(),6)
        options=VariantOptions(**panel.values()).validate()
        self.assertEqual(options.output_width,720)
        self.assertEqual(options.audio_mode,'original')
        self.assertFalse(panel.music_path.isEnabled())
        panel.resolution_preset.setCurrentIndex(2)
        panel.fields['foreground_scale'].setValue(80)
        panel.fields['vertical_position'].setCurrentIndex(1)
        panel.mirror.setChecked(True)
        panel.drop_enabled.setChecked(True)
        panel.drop_every.setValue(30)
        panel.fields['original_volume'].setValue(80)
        panel.fields['watermark_opacity'].setValue(60)
        values=panel.values()
        self.assertEqual(values['output_width'],1280)
        self.assertEqual(values['foreground_scale'],.8)
        self.assertEqual(values['vertical_position'],.25)
        self.assertEqual(values['original_volume'],.8)
        self.assertEqual(values['watermark_opacity'],.6)
        self.assertEqual(values['drop_every'],30)
        self.assertTrue(values['mirror'])
        panel.audio_mode.setCurrentIndex(2)
        self.assertTrue(panel.music_path.isEnabled())
        self.assertEqual(panel.values()['audio_mode'],'mix')
        panel.mask_mode.setCurrentIndex(1)
        self.assertTrue(panel.fields['mask_x'].isEnabled())
        panel.close()
