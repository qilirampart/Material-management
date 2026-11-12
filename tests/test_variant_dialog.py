import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QAbstractSpinBox, QPushButton
from src.variant_dialog import VariantDialog
from src.recreation_page import RecreationPage
from src.upload import build_upload_plan


class VariantDialogTests(unittest.TestCase):
    def test_numeric_controls_have_visible_working_step_buttons(self):
        with tempfile.TemporaryDirectory() as folder:
            dialog = VariantDialog([], folder)
            self.assertEqual(dialog.count.buttonSymbols(), QAbstractSpinBox.NoButtons)
            buttons = {b.accessibleName(): b for b in dialog.findChildren(QPushButton)}
            buttons['增加每条生成数量'].click()
            self.assertEqual(dialog.count.value(), 2)
            buttons['减少每条生成数量'].click()
            self.assertEqual(dialog.count.value(), 1)
            buttons['增加去掉开头'].click()
            self.assertAlmostEqual(dialog.trim_start.value(), .16)
            dialog.processing_group.setEnabled(False)
            self.assertFalse(buttons['增加去掉开头'].isEnabled())
            dialog.close()

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_defaults_and_md5_mode_do_not_request_model_api(self):
        with tempfile.TemporaryDirectory() as folder:
            dialog = VariantDialog([{'video_id': '123', 'path': 'source.mp4', 'drama': '测试剧'}], folder)
            self.assertEqual(dialog.options().mode, 'micro')
            self.assertEqual(dialog.options().background, 'blur')
            self.assertFalse(dialog.import_button.isEnabled())
            dialog.mode.setCurrentIndex(1)
            self.assertEqual(dialog.options().mode, 'md5')
            self.assertFalse(dialog.processing_group.isEnabled())
            dialog.close()

    def test_generated_materials_keep_drama_and_are_not_marked_reviewed(self):
        with tempfile.TemporaryDirectory() as folder:
            page = RecreationPage({'output_root': folder,
                                   'recreation_preferences_path': str(Path(folder) / 'prefs.json')})
            page.drama_input.setPlainText('4100-测试剧')
            page.create_batch()
            path = Path(folder) / 'variant.mp4'
            path.write_bytes(b'video')
            output = {'path': str(path), 'drama': '测试剧', 'mode': 'micro',
                      'metadata': {'video_bitrate_bps': 4_200_000},
                      'source_video_id': '123', 'output_md5': 'abc',
                      'upload_drama_info': {'drama_platform_id': '4100', 'drama_name': '测试剧'}}
            page.receive_outputs({'outputs': [output]})
            page.set_checked(page.output_table, 'all')
            page.prepare_upload()
            row = page.platform.materials[0]
            record = row['record']
            self.assertEqual(row['source']['剧名'], '测试剧')
            self.assertEqual(record['status'], 'review_required')
            self.assertEqual(row['upload_drama_info']['drama_platform_id'], '4100')
            self.assertEqual(record['processing_mode'], 'micro')
            # A fresh detection record must not erase the row's processing identity.
            record.pop('processing_mode')
            plan = build_upload_plan([dict(row, record=record)], drama_name='测试剧',
                                     drama_platform_id='4100', director='王俨', uploader_initials='PSK')
            self.assertTrue(plan[0]['items'][0]['upload_name'].startswith('APP-繁花-王俨-微创新-测试剧-'))
            continued = build_upload_plan([dict(row, record=record)], drama_name='测试剧',
                drama_platform_id='4100', director='王俨', uploader_initials='PSK', sequence_start=51)
            self.assertTrue(continued[0]['items'][0]['upload_name'].endswith('-51.mp4'))
            page.close()
