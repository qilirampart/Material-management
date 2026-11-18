import os
import tempfile
import unittest
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QComboBox
from PySide6.QtCore import QTimer, Qt
from src.recreation_workspace import RecreationWorkspace
from src.recreation_workflow import RecreationWorkflowPage


class MissingBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def fixture(self, root):
        w = RecreationWorkspace(root/'prefs.json', root)
        old, new = w.create('4100-old\n4200-new')
        for b in (old, new):
            b.record_page(b.state['dramas'][0], [{'id': '1', 'name': '二创'}], 1)
            w.add_inputs('md5', b.folder, [b.state['sources'][0]['video_id']])
        (old.folder/'recreation.json').rename(old.folder/'missing.json')
        return w, old, new

    def test_missing_old_batch_does_not_block_new_sources_or_mutate_index(self):
        with tempfile.TemporaryDirectory() as folder:
            w, old, new = self.fixture(Path(folder))
            items = w.resolve_inputs('md5')
            self.assertEqual([x['video_id'] for x in items], ['4200_1'])
            self.assertEqual(len(w.inputs['md5']), 2)
            self.assertEqual(len(w.input_issues['md5']), 1)
            self.assertEqual(w.input_issues['md5'][0]['folder'], str(old.folder))

    def test_missing_source_identity_does_not_block_valid_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            w, old, new = self.fixture(Path(folder))
            w.add_inputs('md5', new.folder, ['removed'])
            self.assertEqual(len(w.resolve_inputs('md5')), 1)
            self.assertEqual(len(w.input_issues['md5']), 2)

    def test_remove_visible_source_uses_identity_not_stale_reference_position(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            w, old, new = self.fixture(root)
            page = RecreationWorkflowPage({'output_root': folder,
                'recreation_preferences_path': str(root/'prefs.json')}, restore=True)
            page.md5.refresh()
            self.assertEqual(page.md5.table.rowCount(), 1)
            page.set_checked(page.md5.table, 'all')
            page.md5.remove_selected()
            self.assertEqual(page.workspace.inputs['md5'], [{'folder': str(old.folder), 'video_id': '4100_1'}])
            page.close()

    def test_deleted_queued_batch_does_not_stop_next_healthy_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            w, old, new = self.fixture(root)
            w.enqueue(old.folder, ['4100_1']); w.enqueue(new.folder, ['4200_1'])
            page = RecreationWorkflowPage({'output_root': folder,
                'recreation_preferences_path': str(root/'prefs.json')}, restore=True)
            with patch.object(page, '_start_browser_task') as start:
                page.resume_download_queue()
                for _ in range(5): self.app.processEvents()
                self.assertEqual(page.batch.folder, new.folder)
                start.assert_called_once_with('download', identities=['4200_1'])
            page.queue_running = False
            page.close()

    def test_batch_removed_during_upload_preparation_releases_busy_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            w, old, new = self.fixture(root)
            page = RecreationWorkflowPage({'output_root': folder,
                'recreation_preferences_path': str(root/'prefs.json')}, restore=True)
            page.upload_groups = [{'folder':str(old.folder),'outputs':[]}]
            page.upload_busy = True
            page.auto_button.setEnabled(False)
            with patch.object(page.platform, 'prepare_upload') as upload:
                page.prepare_next_upload('ws://unused')
                upload.assert_not_called()
            self.assertFalse(page.upload_busy);self.assertTrue(page.auto_button.isEnabled())
            page.close()

    def test_cleanup_cancel_keeps_files_and_busy_cleanup_is_rejected(self):
        from tests.test_recreation_cleanup import CleanupTests
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);w,b,raw,out,cover=CleanupTests().fixture(root)
            page=RecreationWorkflowPage({'output_root':folder,
                'recreation_preferences_path':str(root/'prefs.json')},restore=True)
            page.batch_list.item(0).setCheckState(Qt.Checked)
            def cancel():
                dialog=QApplication.activeModalWidget()
                self.assertIsInstance(dialog,QDialog)
                dialog.findChild(QComboBox).setCurrentIndex(1)
                dialog.reject()
            QTimer.singleShot(0,cancel)
            page.manage_batches()
            self.assertTrue(raw.exists());self.assertTrue(out.exists());self.assertTrue(cover.exists())
            page.cleanup_busy=True
            page.run_batch_cleanup([str(b.folder)],'forget',{})
            self.assertEqual(len(page.workspace.folders),1)
            page.cleanup_busy=False;page.close()

    def test_cleanup_task_updates_visible_catalog_and_releases_ownership(self):
        from tests.test_recreation_cleanup import CleanupTests
        from src.recreation_cleanup import plan_cleanup
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);w,b,raw,out,cover=CleanupTests().fixture(root)
            page=RecreationWorkflowPage({'output_root':folder,
                'recreation_preferences_path':str(root/'prefs.json')},restore=True)
            page.md5.last_output=str(out);page.md5.preview_button.setEnabled(True)
            page.run_batch_cleanup([str(b.folder)],'products',plan_cleanup([b.folder],'products'))
            deadline=time.monotonic()+8
            while page.own_work_in_progress() and time.monotonic()<deadline:
                self.app.processEvents();time.sleep(.01)
            self.assertFalse(page.own_work_in_progress());self.assertTrue(page.cleanup_button.isEnabled())
            self.assertEqual(page.output_table.rowCount(),0);self.assertTrue(raw.exists());self.assertFalse(out.exists())
            self.assertEqual(page.md5.last_output,'');self.assertFalse(page.md5.preview_button.isEnabled())
            page.close()

    def test_processing_refresh_error_restores_table_signals(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.fixture(root)
            page=RecreationWorkflowPage({'output_root':folder,
                'recreation_preferences_path':str(root/'prefs.json')},restore=True)
            with patch.object(page.md5, '_refresh_rows',side_effect=RuntimeError('render failed')):
                with self.assertRaises(RuntimeError):page.md5.refresh()
            self.assertFalse(page.md5.table.signalsBlocked())
            page.close()
