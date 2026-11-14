import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication,QWidget,QDialog
from shiboken6 import delete
from src.micro_settings import MicroSettings
from src.micro_presets import RECOMMENDED,export_preset_package,read_presets,read_preset_package,write_presets
from src.preset_import_dialog import PresetImportDialog


class PresetExchangeUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):self.host=QWidget()
    def tearDown(self):self.host.close();delete(self.host);self.app.processEvents()

    def test_review_lists_missing_resources_and_defaults_to_keep_both(self):
        incoming={'风格':dict(RECOMMENDED,music_path='D:/not-here/test.wav',resource_pools={'background_path':'D:/not-here/images'})}
        d=PresetImportDialog(incoming,{'风格':RECOMMENDED},self.host)
        self.assertFalse(d.replace_existing)
        self.assertEqual(d.tree.topLevelItemCount(),1)
        self.assertEqual(d.tree.topLevelItem(0).childCount(),2)
        self.assertIn('缺少',d.tree.topLevelItem(0).child(0).text(1))
        d.policy.setCurrentIndex(1);self.assertTrue(d.replace_existing)
        d.reject();self.assertEqual(d.result(),QDialog.DialogCode.Rejected)

    def test_import_persists_without_applying_or_replacing_and_cancel_is_noop(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'favorites.json';package=root/'shared.json'
            write_presets(path,{'风格':dict(RECOMMENDED,speed=1)})
            export_preset_package(package,'风格',dict(RECOMMENDED,speed=1.1))
            panel=MicroSettings(presets_path=path);panel.setParent(self.host);before=panel.values()
            with patch('src.micro_settings.QFileDialog.getOpenFileName',return_value=(str(package),'')):
                with patch('src.micro_settings.PresetImportDialog.exec',return_value=QDialog.DialogCode.Rejected):panel.import_presets()
                self.assertEqual(set(read_presets(path)),{'风格'})
                with patch('src.micro_settings.PresetImportDialog.exec',return_value=QDialog.DialogCode.Accepted):panel.import_presets()
            self.assertEqual(panel.values(),before)
            self.assertEqual(panel.preset_combo.currentIndex(),0)
            presets=read_presets(path);self.assertEqual(presets['风格']['speed'],1)
            self.assertEqual(presets['风格（导入）']['speed'],1.1)
            panel.preset_combo.setCurrentText('风格（导入）');panel.apply_selected_preset()
            self.assertEqual(panel.values()['speed'],1.1)

    def test_export_uses_current_unsaved_values_not_selected_favorite(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);panel=MicroSettings(presets_path=root/'favorites.json');panel.setParent(self.host)
            panel.fields['brightness'].setValue(.09)
            target=root/'shared.json'
            with patch('src.micro_settings.QInputDialog.getText',return_value=('当前参数',True)),patch('src.micro_settings.QFileDialog.getSaveFileName',return_value=(str(target),'')):
                panel.export_preset()
            self.assertEqual(read_preset_package(target)['当前参数']['brightness'],.09)
            self.assertFalse((root/'favorites.json').exists())

    def test_export_cannot_overwrite_local_library_and_explicit_replace_keeps_current_values(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'favorites.json';write_presets(path,{'原格式':RECOMMENDED})
            panel=MicroSettings(presets_path=path);panel.setParent(self.host);disk=path.read_bytes()
            with patch('src.micro_settings.QInputDialog.getText',return_value=('导出方案',True)),patch('src.micro_settings.QFileDialog.getSaveFileName',return_value=(str(path),'')):
                panel.export_preset()
            self.assertEqual(path.read_bytes(),disk);self.assertIn('不能覆盖',panel.preset_status.text())
            package=root/'shared.json';export_preset_package(package,'原格式',dict(RECOMMENDED,speed=1.1))
            before=panel.values()
            def replace_review(dialog):
                dialog.policy.setCurrentIndex(1)
                return QDialog.DialogCode.Accepted
            with patch('src.micro_settings.QFileDialog.getOpenFileName',return_value=(str(package),'')),patch('src.micro_settings.PresetImportDialog.exec',new=replace_review):
                panel.import_presets()
            self.assertEqual(list(read_presets(path)),['原格式']);self.assertEqual(read_presets(path)['原格式']['speed'],1.1)
            self.assertEqual(panel.values(),before)

    def test_invalid_import_or_save_failure_preserves_disk_and_visible_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'favorites.json';write_presets(path,{'原格式':RECOMMENDED})
            panel=MicroSettings(presets_path=path);panel.setParent(self.host);before=panel.values();disk=path.read_bytes()
            package=root/'shared.json';package.write_text('broken',encoding='utf-8')
            with patch('src.micro_settings.QFileDialog.getOpenFileName',return_value=(str(package),'')):panel.import_presets()
            self.assertEqual(path.read_bytes(),disk);self.assertEqual(set(panel.presets),{'原格式'})
            export_preset_package(package,'新格式',dict(RECOMMENDED,speed=1.1))
            with patch('src.micro_settings.QFileDialog.getOpenFileName',return_value=(str(package),'')),patch('src.micro_settings.PresetImportDialog.exec',return_value=QDialog.DialogCode.Accepted),patch('src.micro_settings.write_presets',side_effect=OSError('read only')):
                panel.import_presets()
            self.assertEqual(path.read_bytes(),disk);self.assertEqual(panel.values(),before)
            self.assertEqual(set(panel.presets),{'原格式'});self.assertIn('未能导入',panel.preset_status.text())
