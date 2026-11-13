import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from src.micro_settings import MicroSettings
from src.material_variants import VariantOptions


class MicroSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_recommended_default_and_named_favorites_survive_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'favorites.json'
            panel=MicroSettings(presets_path=path)
            values=panel.values()
            self.assertEqual(values['foreground_scale'],.8)
            self.assertEqual(values['speed'],1.06)
            self.assertGreater(values['contrast'],1.05)
            self.assertFalse(values['mirror'])
            panel.fields['brightness'].setValue(.07)
            panel.title.setText('我的标题')
            with patch('src.micro_settings.QInputDialog.getText',return_value=('测试风格',True)):
                panel.save_favorite()
            other=MicroSettings(presets_path=path)
            index=other.preset_combo.findText('测试风格')
            self.assertGreater(index,0)
            other.preset_combo.setCurrentIndex(index)
            other.apply_selected_preset()
            self.assertEqual(other.values()['brightness'],.07)
            self.assertEqual(other.values()['title'],'我的标题')
            other.apply_recommended()
            self.assertEqual(other.values()['brightness'],.02)
            panel.close();other.close()

    def test_stepper_does_not_leave_selected_white_digits(self):
        from src.variant_dialog import VariantDialog
        from PySide6.QtWidgets import QDoubleSpinBox,QPushButton
        spin=QDoubleSpinBox();spin.setValue(1)
        wrapper=VariantDialog._stepper(spin,'测试')
        plus=next(b for b in wrapper.findChildren(QPushButton) if b.text()=='+')
        plus.click()
        self.assertFalse(spin.lineEdit().hasSelectedText())
        wrapper.close()

    def test_favorite_overwrite_requires_confirmation_and_corrupt_file_is_preserved(self):
        from PySide6.QtWidgets import QMessageBox
        from src.micro_presets import read_presets
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'favorites.json'
            panel=MicroSettings(presets_path=path)
            with patch('src.micro_settings.QInputDialog.getText',return_value=('风格',True)):
                panel.save_favorite()
                panel.fields['brightness'].setValue(.08)
                with patch('src.micro_settings.QMessageBox.question',return_value=QMessageBox.No):
                    panel.save_favorite()
                self.assertEqual(read_presets(path)['风格']['brightness'],.02)
                with patch('src.micro_settings.QMessageBox.question',return_value=QMessageBox.Yes):
                    panel.save_favorite()
                self.assertEqual(read_presets(path)['风格']['brightness'],.08)
                path.write_text('broken',encoding='utf-8')
                panel.save_favorite()
                self.assertEqual(path.read_text(encoding='utf-8'),'broken')
                self.assertIn('未能收藏',panel.preset_status.text())
            panel.close()

    def test_all_six_categories_round_trip_even_when_attachment_moves(self):
        from PySide6.QtWidgets import QMessageBox
        from src.micro_presets import RECOMMENDED
        with tempfile.TemporaryDirectory() as folder:
            image=Path(folder)/'logo.png';image.write_bytes(b'image')
            music=Path(folder)/'music.wav';music.write_bytes(b'audio')
            path=Path(folder)/'favorites.json'
            panel=MicroSettings(presets_path=path)
            values=dict(RECOMMENDED,output_width=1000,output_height=1400,background='black',
                foreground_scale=.75,mirror=True,rotation=90,crop_percent=2,
                color_adjust=False,sharpen=.8,denoise=2,trim_start=1,trim_end=2,speed=.95,
                output_fps=24,drop_every=30,title='收藏标题',title_position='bottom_left',title_size=36,
                title_color='FFE05D',watermark_path=str(image),watermark_position='bottom_right',
                watermark_scale=.2,watermark_opacity=.6,audio_mode='mix',music_path=str(music),
                original_volume=.8,music_volume=.4,mask_mode='blur',mask_x=10,mask_y=15,mask_w=30,mask_h=25)
            panel.apply_settings(values)
            self.assertEqual(panel.values(),values)
            with patch('src.micro_settings.QInputDialog.getText',return_value=('完整参数',True)):
                panel.save_favorite()
            music.unlink()
            other=MicroSettings(presets_path=path)
            other.preset_combo.setCurrentText('完整参数');other.apply_selected_preset()
            self.assertEqual(other.values(),values)
            self.assertIn('文件已移动',other.preset_status.text())
            with patch('src.micro_settings.QMessageBox.question',return_value=QMessageBox.Yes):
                other.delete_favorite()
            self.assertEqual(other.values(),values)
            self.assertNotIn('完整参数',other.presets)
            panel.close();other.close()

    def test_composition_and_random_settings_round_trip_and_are_favoritable(self):
        from src.micro_presets import RECOMMENDED
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'presets.json'
            panel=MicroSettings(presets_path=path)
            values=dict(RECOMMENDED,zoom_mode='pulse',zoom_amount=.12,zoom_period=4,
                intro_duration=2,outro_duration=4,transition='wipeleft',transition_duration=.4,bookend_audio=False,
                pip_scale=.3,pip_x=.5,pip_y=.75,pip_opacity=.7,randomize=True,random_seed=22,
                random_ranges={'foreground_scale':[.6,.9],'speed':[1,1.1],'contrast':[1.1,1.3]},
                resource_pools={'background_path':folder})
            panel.apply_settings(values)
            self.assertEqual(panel.values(),values)
            with patch('src.micro_settings.QInputDialog.getText',return_value=('动态方案',True)):
                panel.save_favorite()
            other=MicroSettings(presets_path=path)
            other.preset_combo.setCurrentText('动态方案');other.apply_selected_preset()
            self.assertEqual(other.values(),values)
            panel.close();other.close()

    def test_all_six_categories_have_valid_defaults_and_map_values(self):
        panel=MicroSettings()
        self.assertEqual(panel.tabs.count(),9)
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
