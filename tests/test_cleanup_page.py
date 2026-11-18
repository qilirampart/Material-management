import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication, QMessageBox
from src.recreation_workflow import RecreationWorkflowPage
from tests import test_recreation_cleanup as fixtures


class CleanupPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait(self, condition):
        end = time.monotonic()+8
        while not condition() and time.monotonic()<end:
            self.app.processEvents(); time.sleep(.01)
        self.assertTrue(condition())

    def test_sixth_step_selection_preview_delete_syncs_all_consumers(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); w,b,raw,out,cover=fixtures.CleanupTests().fixture(root)
            page=RecreationWorkflowPage({'output_root':folder,
                'recreation_preferences_path':str(w.path)},restore=True)
            self.assertEqual(page.tabs.tabText(5),'06  文件清理')
            page.tabs.setCurrentIndex(5)
            cleanup=page.file_cleanup
            index=cleanup.model.index(str(raw))
            self.wait(lambda: index.isValid())
            cleanup.tree.selectionModel().select(index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
            cleanup.prepare()
            self.wait(lambda: not page.work_in_progress())
            self.assertEqual(cleanup.plan['files'],1)
            self.assertIn(str(raw),cleanup.preview.toPlainText())
            self.assertTrue(cleanup.delete_button.isEnabled())
            with patch('src.recreation_cleanup_page.QMessageBox.question',return_value=QMessageBox.Yes):
                cleanup.confirm()
            self.wait(lambda: not page.work_in_progress())
            self.assertFalse(raw.exists()); self.assertTrue(out.exists())
            self.assertEqual(page.workspace.inputs,{'md5':[],'micro':[]})
            self.assertEqual(page.md5.table.rowCount(),0)
            self.assertEqual(page.output_table.rowCount(),1)
            self.assertIsNone(cleanup.plan)
            self.assertIn('清理完成',cleanup.status.text())
            page.close(); page.deleteLater(); self.app.processEvents()

    def test_root_change_and_running_task_prevent_stale_delete(self):
        with tempfile.TemporaryDirectory() as folder:
            page=RecreationWorkflowPage({'output_root':folder,
                'recreation_preferences_path':str(Path(folder)/'prefs.json')},restore=False)
            cleanup=page.file_cleanup
            cleanup.plan={'files':1,'batches':[{}]}
            with patch.object(page,'work_in_progress',return_value=True), \
                    patch('src.recreation_cleanup_page.QMessageBox.question') as ask:
                cleanup.confirm(); ask.assert_not_called()
            page.apply_config({'output_root':str(Path(folder)/'new')})
            self.assertEqual(cleanup.root, (Path(folder)/'new').resolve())
            self.assertIsNone(cleanup.plan)
            page.close(); page.deleteLater(); self.app.processEvents()

    def test_historical_file_not_in_current_list_can_be_previewed_and_stale_preview_clears(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); w,b,raw,out,cover=fixtures.CleanupTests().fixture(root)
            page=RecreationWorkflowPage({'output_root':folder,
                'recreation_preferences_path':str(root/'empty-index.json')},restore=False)
            self.assertEqual(page.workspace.folders,[])
            cleanup=page.file_cleanup
            index=cleanup.model.index(str(raw))
            self.wait(lambda:index.isValid())
            cleanup.tree.selectionModel().select(index,QItemSelectionModel.ClearAndSelect|QItemSelectionModel.Rows)
            cleanup.prepare(); self.wait(lambda:not page.work_in_progress())
            self.assertEqual(cleanup.plan['files'],1)
            self.assertTrue(cleanup.delete_button.isEnabled())
            cleanup.tree.clearSelection()
            self.assertIsNone(cleanup.plan)
            self.assertEqual(cleanup.preview.toPlainText(),'')
            self.assertFalse(cleanup.delete_button.isEnabled())
            page.close(); page.deleteLater(); self.app.processEvents()

    def test_visible_guide_explains_selection_preview_confirmation_and_file_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            page=RecreationWorkflowPage({'output_root':folder,
                'recreation_preferences_path':str(Path(folder)/'prefs.json')},restore=False)
            cleanup=page.file_cleanup
            guide=cleanup.guide.text()
            for text in ('1.', '文件夹', '视频文件', '2.', '预览待删除文件', '数量', '大小', '3.', '按钮才会启用'):
                self.assertIn(text,guide)
            for text in ('MP4', '配套封面', '文档', '批次记录', '不删除'):
                self.assertIn(text,cleanup.safety_notice.text())
            self.assertEqual(cleanup.preview_button.text(),'预览待删除文件')
            page.close();page.deleteLater();self.app.processEvents()

    def test_missing_directory_is_not_a_drive_browser_and_can_be_created_after_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'not-created'/'materials'
            page=RecreationWorkflowPage({'output_root':str(root),
                'recreation_preferences_path':str(Path(folder)/'prefs.json')},restore=False)
            cleanup=page.file_cleanup
            self.assertIsNone(cleanup.tree.model())
            self.assertFalse(cleanup.preview_button.isEnabled())
            with patch('src.recreation_cleanup_page.QMessageBox.question',return_value=QMessageBox.No), \
                    patch('src.recreation_cleanup_page.QDesktopServices.openUrl') as opener:
                cleanup.open_root();opener.assert_not_called()
            self.assertFalse(root.exists())
            with patch('src.recreation_cleanup_page.QMessageBox.question',return_value=QMessageBox.Yes), \
                    patch('src.recreation_cleanup_page.QDesktopServices.openUrl',return_value=True) as opener:
                cleanup.open_root();opener.assert_called_once()
            self.assertTrue(root.is_dir())
            self.assertIsNotNone(cleanup.tree.model())
            self.assertEqual(Path(cleanup.model.filePath(cleanup.tree.rootIndex())),root.resolve())
            page.close();page.deleteLater();self.app.processEvents()

    def test_open_directory_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            page=RecreationWorkflowPage({'output_root':folder,
                'recreation_preferences_path':str(Path(folder)/'prefs.json')},restore=False)
            with patch('src.recreation_cleanup_page.QDesktopServices.openUrl',return_value=False), \
                    patch('src.recreation_cleanup_page.QMessageBox.warning') as warning:
                page.file_cleanup.open_root();warning.assert_called_once()
            page.close();page.deleteLater();self.app.processEvents()
