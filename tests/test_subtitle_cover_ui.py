import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication,QWidget,QDialog,QPushButton
from shiboken6 import delete
from src.subtitle_cover_dialog import SubtitleCoverDialog
from src.subtitle_cover import SUBTITLE_DEFAULTS
from src.micro_settings import MicroSettings
from src.micro_presets import read_presets,RECOMMENDED,validate_settings


class SubtitleCoverUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):self.host=QWidget()
    def tearDown(self):self.host.close();delete(self.host);self.app.processEvents()

    def test_cancel_works_on_copy_and_ass_style_and_cover_controls_follow_choices(self):
        values=dict(SUBTITLE_DEFAULTS)
        d=SubtitleCoverDialog(values,self.host)
        d.fields['subtitle_path'].setText('missing.ass')
        self.assertFalse(d.style_widget.isEnabled())
        d.keep.setChecked(False);self.assertTrue(d.style_widget.isEnabled())
        d.fields['cover_mode'].setCurrentIndex(2)
        self.assertTrue(d.fields['cover_time'].parentWidget().isEnabled())
        self.assertFalse(d.fields['cover_path'].parentWidget().isEnabled())
        d.save();self.assertNotEqual(d.result(),QDialog.DialogCode.Accepted)
        self.assertIn('字幕',d.status.text())
        d.reject();self.assertEqual(values,SUBTITLE_DEFAULTS)

    def test_save_and_cancel_stay_visible_on_both_tabs(self):
        d=SubtitleCoverDialog(SUBTITLE_DEFAULTS,self.host);d.resize(680,650);d.show()
        for index in (0,1,0):
            d.tabs.setCurrentIndex(index);self.app.processEvents()
            for b in d.findChildren(QPushButton):
                if b.text() in {'保留设置','取消'}:
                    point=b.mapTo(d,b.rect().bottomRight())
                    self.assertLessEqual(point.y(),d.height());self.assertLessEqual(point.x(),d.width())
        d.reject()

    def test_favorites_keep_paths_when_moved_and_old_favorites_get_disabled_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            subtitle=Path(folder)/'cn.srt';subtitle.write_text('test',encoding='utf-8')
            path=Path(folder)/'favorites.json'
            panel=MicroSettings(presets_path=path);panel.setParent(self.host)
            d=SubtitleCoverDialog(panel.subtitle_cover,self.host)
            d.fields['subtitle_path'].setText(str(subtitle));d.fields['subtitle_shift'].setValue(.3)
            d.fields['cover_mode'].setCurrentIndex(2);d.fields['cover_time'].setValue(2)
            d.save();self.assertEqual(d.result(),QDialog.DialogCode.Accepted)
            panel.subtitle_cover=d.settings
            with patch('src.micro_settings.QInputDialog.getText',return_value=('字幕封面方案',True)):panel.save_favorite()
            subtitle.unlink()
            other=MicroSettings(presets_path=path);other.setParent(self.host)
            other.apply_settings(read_presets(path)['字幕封面方案'])
            self.assertEqual(other.values(),panel.values())
            legacy={k:v for k,v in RECOMMENDED.items() if k not in SUBTITLE_DEFAULTS}
            migrated=validate_settings(legacy)
            self.assertEqual(migrated['subtitle_path'],'');self.assertEqual(migrated['cover_mode'],'none')
            with self.assertRaises(ValueError):validate_settings(dict(RECOMMENDED,cover_mode='oops'))
