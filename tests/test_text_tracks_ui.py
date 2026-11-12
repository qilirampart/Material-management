import os
import tempfile
import unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication,QDialog,QWidget
from shiboken6 import delete
from PySide6.QtCore import QTimer
from src.text_tracks_dialog import TextTracksDialog
from src.micro_settings import MicroSettings
from src.text_tracks import normalize_track
from unittest.mock import patch


class TextTracksUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):self.host=QWidget()

    def tearDown(self):
        self.host.close()
        delete(self.host)
        self.app.processEvents()

    def test_switch_add_remove_save_and_cancel_do_not_mutate_input(self):
        original=[normalize_track({'text':'第一轨'}),normalize_track({'text':'第二轨'})]
        dialog=TextTracksDialog(original,self.host)
        dialog.text.setPlainText('改过的第一轨')
        dialog.listing.setCurrentRow(1)
        dialog.fields['start'].setValue(2)
        dialog.add_track()
        self.assertEqual(len(dialog.tracks),3)
        dialog.remove_track()
        dialog.accept()
        self.assertEqual(dialog.result(),QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.tracks[0]['text'],'改过的第一轨')
        self.assertEqual(dialog.tracks[1]['start'],2)
        self.assertEqual(original[0]['text'],'第一轨')
        cancelled=TextTracksDialog(original,self.host)
        cancelled.text.setPlainText('不保存');cancelled.reject()
        self.assertEqual(original[0]['text'],'第一轨')

    def test_empty_track_is_rejected_and_settings_snapshot_is_independent(self):
        dialog=TextTracksDialog([],self.host)
        dialog.add_track();dialog.text.clear();dialog.accept()
        self.assertIn('需有内容',dialog.status.text())
        self.assertEqual(dialog.result(),0)
        dialog.reject()
        with tempfile.TemporaryDirectory() as folder:
            panel=MicroSettings(presets_path=Path(folder)/'presets.json')
            panel.setParent(self.host)
            panel.text_tracks=[normalize_track({'text':'收藏文字','duration':2})]
            panel.fields['music_delay'].setValue(1)
            values=panel.values()
            values['text_tracks'][0]['text']='changed'
            self.assertEqual(panel.text_tracks[0]['text'],'收藏文字')
            panel.fields['watermark_start'].setValue(2)
            panel.fields['watermark_duration'].setValue(3)
            with patch('src.micro_settings.QInputDialog.getText',return_value=('定时文字',True)):
                panel.save_favorite()
            other=MicroSettings(presets_path=Path(folder)/'presets.json')
            other.setParent(self.host)
            other.preset_combo.setCurrentText('定时文字');other.apply_selected_preset()
            self.assertEqual(other.values()['text_tracks'],panel.values()['text_tracks'])
            self.assertEqual(other.values()['music_delay'],1)
            self.assertEqual(other.values()['watermark_start'],2)
            self.assertEqual(other.values()['watermark_duration'],3)
            other.close()
            panel.close()

    def test_main_settings_entry_applies_the_saved_dialog_result(self):
        panel=MicroSettings()
        panel.setParent(self.host)
        def edit():
            dialog=self.app.activeModalWidget()
            dialog.add_track();dialog.text.setPlainText('通过主入口保存')
            dialog.accept()
        QTimer.singleShot(0,edit)
        panel.edit_text_tracks()
        self.assertEqual(panel.values()['text_tracks'][0]['text'],'通过主入口保存')
        self.assertIn('1',panel.tracks_button.text())
        self.app.processEvents();panel.close()
