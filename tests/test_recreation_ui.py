import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from src.desktop import MainWindow
from src.recreation_page import RecreationPage


class RecreationUiTests(unittest.TestCase):
    def test_refresh_keeps_selected_sources_and_retry_is_visible(self):
        with tempfile.TemporaryDirectory() as folder:
            page = RecreationPage({'output_root': folder,
                                   'recreation_preferences_path': str(Path(folder) / 'prefs.json')})
            page.drama_input.setPlainText('4100-测试剧')
            page.create_batch()
            page.batch.record_page(page.batch.state['dramas'][0], [{'id': '1', 'name': '二创'}], 1)
            page.refresh_sources()
            page.source_table.selectRow(0)
            page._sync_collection_state()
            self.assertEqual([x.row() for x in page.source_table.selectionModel().selectedRows()], [0])
            page.show_collection_progress({'phase': 'downloading', 'video_id': '4100_1',
                'index': 1, 'total': 1, 'drama': '测试剧', 'bytes': 0, 'size': 0,
                'speed': 0, 'retry': 1})
            self.assertIn('重试', page.collection_status.text())
            page.close()

    def test_changed_drama_input_does_not_silently_query_old_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            page = RecreationPage({'output_root': folder,
                                   'recreation_preferences_path': str(Path(folder) / 'prefs.json')})
            page.drama_input.setPlainText('4100-测试剧')
            page.create_batch()
            page.drama_input.setPlainText('4200-另一剧')
            with patch.object(page, '_start_browser_task') as start:
                page.query_materials()
                start.assert_not_called()
            self.assertIn('创建新批次', page.message.text())
            page.close()

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_new_workflow_does_not_reuse_original_rows_or_upload_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            window = MainWindow(restore=False)
            original_rows = list(window.rows)
            original_folder = window.folder
            original_last_batch = window.config.get('last_batch')
            page = window.recreation
            page.output_root = Path(folder)
            page.preferences_path = Path(folder) / 'preferences.json'
            page.drama_input.setPlainText('4100-测试剧')
            page.create_batch()
            path = Path(folder) / '精剪原片.mp4'
            path.write_bytes(b'video')
            page.batch.add_local_sources([str(path)], page.batch.state['dramas'][0])
            page.refresh_sources()
            self.assertEqual(window.rows, original_rows)
            self.assertEqual(window.folder, original_folder)
            self.assertEqual(window.config.get('last_batch'), original_last_batch)
            self.assertNotEqual(page.platform.preferences_path, window.platform.preferences_path)
            self.assertEqual(page.platform.upload_departments, ['客户端二组'])
            self.assertIsNone(window.platform.upload_departments)
            self.assertTrue(page.query_button.isEnabled())
            self.assertFalse(hasattr(window, 'variant_button'))
            window.close()

    def test_query_defaults_cover_history_and_current_download_state_is_not_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            page = RecreationPage({'output_root': folder,
                                   'recreation_preferences_path': str(Path(folder) / 'prefs.json')})
            page.drama_input.setPlainText('4100-测试剧')
            page.create_batch()
            self.assertEqual(page.date_start.date().toString('yyyy-MM-dd'), '2014-01-01')
            page.batch.record_page(page.batch.state['dramas'][0], [{'id': '1', 'name': '二创'}], 1)
            page.batch.begin_download('4100_1')
            page._sync_collection_state()
            self.assertEqual(page.batch.state['sources'][0]['download_status'], 'downloading')
            page._set_collection_busy(True)
            self.assertFalse(page.query_button.isEnabled())
            self.assertTrue(page.stop_button.isEnabled())
            page._set_collection_busy(False)
            page.close()

    def test_upload_preparation_is_per_drama_and_does_not_change_original_upload(self):
        with tempfile.TemporaryDirectory() as folder:
            config = {'output_root': folder, 'recreation_preferences_path': str(Path(folder) / 'prefs.json')}
            page = RecreationPage(config)
            page.drama_input.setPlainText('4100-测试剧\n4200-第二剧')
            page.create_batch()
            source = Path(folder) / 'output.mp4'
            source.write_bytes(b'video')
            outputs = []
            for drama_id, name in [('4100', '测试剧'), ('4200', '第二剧')]:
                path = source.with_name(drama_id + '.mp4')
                path.write_bytes(b'video')
                outputs.append({'path': str(path), 'drama': name, 'mode': 'micro',
                    'metadata': {'video_bitrate_bps': 4_200_000},
                    'upload_drama_info': {'drama_platform_id': drama_id, 'drama_name': name}})
            page.receive_outputs({'outputs': outputs})
            page.output_table.selectAll()
            page.prepare_upload()
            self.assertEqual(len(page.platform.materials), 1)
            self.assertEqual(page.platform.materials[0]['upload_drama_info']['drama_platform_id'], '4100')
            self.assertEqual(page.platform.materials[0]['record']['status'], 'review_required')
            self.assertTrue((page.batch.folder / 'recreation.json').is_file())
            page.close()
