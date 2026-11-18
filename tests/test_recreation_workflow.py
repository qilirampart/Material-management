import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from src.recreation_workflow import RecreationWorkflowPage
from src.recreation import RecreationBatch
from src.media import run


class WorkflowTests(unittest.TestCase):
    def test_local_import_uses_dialog_batch_not_current_download_batch(self):
        from PySide6.QtWidgets import QDialog
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            page.drama_input.setPlainText('4100-第一剧\n4200-第二剧')
            page.create_batch()
            other = page.workspace.folders[1]
            source = Path(folder) / 'local.mp4'
            source.write_bytes(b'video')
            with patch('src.recreation_workflow.QFileDialog.getOpenFileNames', return_value=([str(source)], '')):
                page.import_processing_local('md5', QDialog(page), other)
            self.assertEqual(page.md5.items[0]['drama_id'], '4200')
            self.assertEqual(RecreationBatch.load(page.workspace.folders[0]).state['sources'], [])
            page.close()
    def test_changed_workspace_paths_are_respected_before_creating_or_remembering_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            original_root = Path(folder) / 'original'
            original_root.mkdir()
            page = self.page(str(original_root))
            new_root = Path(folder) / 'new'
            page.output_root = new_root
            page.preferences_path = new_root / 'prefs.json'
            page.drama_input.setPlainText('4100-测试剧')
            page.create_batch()
            self.assertTrue(page.batch.folder.is_relative_to(new_root.resolve()))
            self.assertTrue(page.preferences_path.is_file())
            self.assertFalse((original_root / 'prefs.json').exists())
            self.assertEqual(page.workspace.path, page.preferences_path)
            page.close()
    def test_successful_upload_is_durable_and_duplicate_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            page.drama_input.setPlainText('4100-测试剧')
            page.create_batch()
            path = Path(folder) / 'ready.mp4'
            path.write_bytes(b'video')
            output = {'path': str(path), 'drama': '测试剧', 'mode': 'md5', 'metadata': {},
                      'upload_drama_info': {'drama_platform_id': '4100', 'drama_name': '测试剧'}}
            page.batch.add_outputs([output])
            group = {'folder': str(page.batch.folder), 'drama_id': '4100', 'drama': '测试剧', 'outputs': [output]}
            page.current_upload, page.upload_groups = group, [group]
            page.upload_completed({'uploaded': 1, 'stopped': False})
            self.assertEqual(RecreationBatch.load(page.batch.folder).state['uploads'][0]['submitted'], False)
            self.assertTrue(page.catalog[0]['uploaded_before'])
            page.set_checked(page.output_table, 'all')
            with patch('src.recreation_workflow.QMessageBox.question', return_value=QMessageBox.No), \
                    patch.object(page, 'continue_upload') as upload:
                page.begin_upload()
                upload.assert_not_called()
            page.close()

    def test_download_queue_pauses_durably_and_advances_between_independent_batches(self):
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            batches = page.workspace.create('4100-第一剧\n4200-第二剧')
            for batch in batches:
                batch.record_page(batch.state['dramas'][0], [{'id': '1', 'name': '二创'}], 1)
                page.workspace.enqueue(batch.folder, [batch.state['dramas'][0]['id'] + '_1'])
            def start(*args, **kwargs):
                page._set_collection_busy(True)
            with patch.object(page, '_start_browser_task', side_effect=start) as worker:
                page.resume_download_queue()
                self.assertEqual(page.batch.state['dramas'][0]['id'], '4100')
                page.stop_collection()
                page.collection_result({'completed': 0, 'failed': 0, 'skipped': 0, 'stopped': True})
                page.collection_finished()
                self.assertEqual(len(page.workspace.queue), 2)
                self.assertFalse(page.queue_running)
                page.resume_download_queue()
                page.collection_result({'completed': 1, 'failed': 0, 'skipped': 0, 'stopped': False})
                page.collection_finished()
                self.app.processEvents()
                self.assertEqual(page.batch.state['dramas'][0]['id'], '4200')
                self.assertEqual(len(page.workspace.queue), 1)
                page.collection_failed('测试中断')
                page.collection_finished()
                self.assertFalse(page.queue_running)
                self.assertEqual(worker.call_count, 3)
            page.close()

    def test_upload_preflight_refuses_unsaved_form_before_any_file_selection(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            page.platform.browser = Mock()
            page.platform.browser.page.return_value.devToolsId.return_value = 'target'
            page.upload_groups = [{'folder': folder, 'drama_id': '4100', 'drama': '测试剧', 'outputs': []}]
            with patch('src.recreation_workflow.find_page_ws_url', return_value='ws://test'), \
                 patch('src.recreation_workflow.evaluate_edge_page', return_value={'unsaved': True}), \
                 patch.object(page.platform, 'fill_platform_form') as fill:
                page.continue_upload()
                deadline = time.monotonic()+5
                while page.upload_busy and time.monotonic()<deadline:
                    self.app.processEvents()
                    time.sleep(.01)
                self.assertFalse(page.upload_busy)
                self.assertIn('不会覆盖', page.message.text())
                fill.assert_not_called()
            page.platform.browser = None
            page.close()

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def page(self, folder):
        return RecreationWorkflowPage({'output_root': folder, 'recreation_preferences_path': str(Path(folder) / 'prefs.json')}, restore=False)

    def test_six_stages_share_one_platform_component_and_separate_batches(self):
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            self.assertEqual(page.tabs.count(), 6)
            page.drama_input.setPlainText('4100-第一剧\n4200-第二剧')
            page.create_batch()
            self.assertEqual(page.batch_list.count(), 2)
            page.show()
            page.tabs.setCurrentIndex(1)
            self.app.processEvents()
            self.assertTrue(page.source_table.isVisible())
            self.assertEqual(len(page.batch.state['dramas']), 1)
            page.batch_list.setCurrentRow(1)
            self.assertEqual(page.batch.state['dramas'][0]['id'], '4200')
            self.assertIs(page.platform.browser_card.parentWidget(), page.tabs.widget(0))
            self.assertEqual(page.platform.upload_departments, ['客户端二组'])
            page.close()

    def test_pending_source_requires_consent_and_only_successful_downloads_are_imported(self):
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            page.drama_input.setPlainText('4100-测试剧')
            page.create_batch()
            batch = page.batch
            batch.record_page(batch.state['dramas'][0], [{'id': '1', 'name': '二创'}, {'id': '2', 'name': '二创'}], 1)
            with patch('src.recreation_workflow.QMessageBox.question', return_value=QMessageBox.No), \
                    patch.object(page, '_start_browser_task') as start:
                page.request_processing_import('md5', str(batch.folder), ['4100_1'])
                start.assert_not_called()
                self.assertEqual(page.workspace.inputs['md5'], [])
            with patch('src.recreation_workflow.QMessageBox.question', return_value=QMessageBox.Yes), \
                    patch.object(page, '_start_browser_task', side_effect=lambda *a, **k: page._set_collection_busy(True)) as start:
                page.request_processing_import('md5', str(batch.folder), ['4100_1', '4100_2'])
                self.assertEqual(start.call_args.kwargs['identities'], ['4100_1', '4100_2'])
            source = Path(folder) / 'source.mp4'
            source.write_bytes(b'video')
            batch = RecreationBatch.load(batch.folder)
            batch.state['sources'][0].update(path=str(source), download_status='downloaded')
            batch.save()
            page.collection_result({'completed': 1, 'failed': 1, 'skipped': 0, 'stopped': False})
            page.collection_finished()
            self.assertEqual([x['video_id'] for x in page.workspace.inputs['md5']], ['4100_1'])
            self.assertEqual(page.workspace.inputs['micro'], [])
            self.assertEqual(page.md5.table.rowCount(), 1)
            page.close()

    def test_real_md5_processing_persists_to_source_batch_and_appears_in_upload(self):
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            page.drama_input.setPlainText('4100-测试剧')
            page.create_batch()
            source = Path(folder) / 'source.mp4'
            run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x240:rate=15:duration=1', '-c:v', 'libx264', str(source)])
            page.batch.add_local_sources([str(source)], page.batch.state['dramas'][0])
            identity = page.batch.state['sources'][0]['video_id']
            page.complete_processing_import('md5', str(page.batch.folder), [identity])
            page.md5.uploader.setText('TEST')
            page.set_checked(page.md5.table, 'all')
            page.md5.start()
            deadline = time.monotonic() + 15
            while page.md5.busy and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.01)
            self.assertFalse(page.md5.busy)
            self.assertEqual(len(RecreationBatch.load(page.batch.folder).state['outputs']), 1, page.md5.status.text())
            self.assertEqual(len(page.catalog), 1)
            self.assertEqual(page.catalog[0]['mode'], 'md5')
            page.view_products('micro')
            self.assertEqual(page.output_table.rowCount(), 0)
            page.view_products('md5')
            self.assertEqual(page.output_table.rowCount(), 1)
            page.close()

    def test_effect_preview_plays_without_registering_product_or_requiring_uploader(self):
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            page.drama_input.setPlainText('4100-测试剧')
            page.create_batch()
            source = Path(folder)/'source.mp4'
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=30:duration=4',
                 '-c:v','libx264',str(source)])
            page.batch.add_local_sources([str(source)],page.batch.state['dramas'][0])
            identity = page.batch.state['sources'][0]['video_id']
            page.complete_processing_import('micro',str(page.batch.folder),[identity])
            panel = page.micro
            page.set_checked(panel.table,'all')
            panel.preview_length.setValue(2)
            panel.preview_start.setValue(1)
            panel.micro_settings.mirror.setChecked(True)
            panel.micro_settings.randomize.setChecked(True)
            panel.start(preview=True)
            deadline = time.monotonic()+20
            while panel.busy and time.monotonic()<deadline:
                self.app.processEvents()
                time.sleep(.01)
            self.assertFalse(panel.busy)
            self.assertIsNotNone(panel.preview_dialog,panel.status.text())
            self.assertEqual(RecreationBatch.load(page.batch.folder).state['outputs'],[])
            self.assertEqual(page.catalog,[])
            self.assertTrue(panel.micro_settings.mirror.isChecked())
            self.assertTrue(panel.effect_button.isEnabled())
            self.assertTrue(panel.preview_dialog.player.source().isLocalFile())
            cache = Path(panel.preview_cache.name)
            self.assertTrue((cache/'preview.mp4').is_file())
            panel.preview_dialog.accept()
            self.assertIsNone(panel.preview_dialog.player)
            self.assertFalse(cache.exists())
            panel.uploader.setText('TEST');panel.count.setValue(2)
            for change in (False,True):
                if change:panel.micro_settings.fields['brightness'].setValue(.08)
                with patch('src.recreation_processing.generate_variants',return_value={'outputs':[],'failed':[]}) as generate:
                    panel.start()
                    deadline=time.monotonic()+10
                    while panel.busy and time.monotonic()<deadline:
                        self.app.processEvents();time.sleep(.01)
                frozen=generate.call_args.kwargs['resolved_plans']
                self.assertEqual(len(frozen),0 if change else 1)
            panel.preview_start.setValue(100)
            panel.start(preview=True)
            deadline = time.monotonic()+10
            while panel.busy and time.monotonic()<deadline:
                self.app.processEvents()
                time.sleep(.01)
            self.assertIn('预览起点',panel.status.text())
            self.assertEqual(RecreationBatch.load(page.batch.folder).state['outputs'],[])
            panel.preview_cache.cleanup()
            page.close()

    def test_upload_groups_do_not_mix_dramas_or_exceed_fifty(self):
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            path = Path(folder) / 'ready.mp4'
            path.write_bytes(b'video')
            page.catalog = [{'path': str(path), 'batch_folder': folder, 'mode': 'md5', 'drama': drama,
                'metadata': {}, 'upload_drama_info': {'drama_platform_id': identity, 'drama_name': drama}}
                for identity, drama, n in [('4100', '第一剧', 51), ('4200', '第二剧', 2)] for _ in range(n)]
            page.output_table.setRowCount(53)
            for i in range(53):
                page.output_table.setItem(i, 0, page._check_item(str(i), {str(i)}))
            page.platform.director.setText('编导')
            page.platform.uploader_initials.setText('TEST')
            with patch.object(page, 'continue_upload'):
                page.begin_upload()
            self.assertEqual([len(x['outputs']) for x in page.upload_groups], [50, 1, 2])
            self.assertEqual([x['drama_id'] for x in page.upload_groups], ['4100', '4100', '4200'])
            self.assertEqual([x['sequence_start'] for x in page.upload_groups], [1, 51, 1])
            page.close()
