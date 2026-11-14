import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QWidget,QDialog
from shiboken6 import delete
from src.recovery_dialog import RecoveryDialog
from src.recreation import RecreationBatch
from src.recreation_workflow import RecreationWorkflowPage
from tests import test_recreation_recovery as fixtures


class RecoveryUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):self.host=QWidget()
    def tearDown(self):self.host.close();delete(self.host);self.app.processEvents()
    def settle(self,dialog):
        deadline=time.monotonic()+20
        while dialog.busy and time.monotonic()<deadline:self.app.processEvents();time.sleep(.01)
        self.assertFalse(dialog.busy)

    def test_real_inspection_selection_and_save_are_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            batch,manifest,output=fixtures.RecoveryTests().fixture(Path(folder))
            d=RecoveryDialog(manifest,self.host);d.show();self.settle(d)
            self.assertEqual(RecreationBatch.load(batch.folder).state['outputs'],[])
            self.assertTrue(d.save_button.isEnabled());self.assertEqual(d.table.item(0,0).checkState(),Qt.Checked)
            d.select_ready(False);self.assertFalse(d.save_button.isEnabled())
            d.select_ready(True);d.restore_selected();self.settle(d)
            self.assertEqual(d.saved_count,1);self.assertFalse(d.save_button.isEnabled())
            self.assertEqual(len(RecreationBatch.load(batch.folder).state['outputs']),1);d.reject()

    def test_close_while_validating_waits_for_worker_and_does_not_save(self):
        with tempfile.TemporaryDirectory() as folder:
            batch,manifest,output=fixtures.RecoveryTests().fixture(Path(folder))
            d=RecoveryDialog(manifest,self.host);d.reject();self.settle(d)
            self.assertEqual(d.result(),QDialog.DialogCode.Rejected)
            self.assertEqual(RecreationBatch.load(batch.folder).state['outputs'],[])

    def test_workflow_restores_original_batch_without_touching_other_batch_or_uploading(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);batch,manifest,output=fixtures.RecoveryTests().fixture(root)
            page=RecreationWorkflowPage({'output_root':str(root),'recreation_preferences_path':str(root/'workspace.json')},restore=False)
            page.setParent(self.host);page.drama_input.setPlainText('4200-另一剧');page.create_batch()
            other=page.batch.folder
            def run_dialog(dialog):
                self.settle(dialog);dialog.restore_selected();self.settle(dialog)
                return QDialog.DialogCode.Accepted
            with patch('src.recreation_workflow.QFileDialog.getOpenFileName',return_value=(str(manifest),'')),patch('src.recreation_workflow.RecoveryDialog.exec',new=run_dialog),patch.object(page,'begin_upload') as upload:
                page.recover_products()
                self.assertFalse(upload.called)
            self.assertEqual(page.batch.folder,other)
            self.assertEqual(RecreationBatch.load(other).state['outputs'],[])
            self.assertEqual(len(page.catalog),1);self.assertEqual(page.catalog[0]['path'],output['path'])
            self.assertEqual(page.checked_rows(page.output_table),[])
