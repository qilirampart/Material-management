import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QWidget
from shiboken6 import delete
from src.recreation import RecreationBatch
from src.recreation_workflow import RecreationWorkflowPage


class NameFilterUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):self.host=QWidget()
    def tearDown(self):self.host.close();delete(self.host);self.app.processEvents()
    def page(self,root):
        page=RecreationWorkflowPage({'output_root':str(root),'recreation_preferences_path':str(Path(root)/'prefs.json')},restore=False)
        page.setParent(self.host);return page

    def test_new_batch_defaults_to_square_name_exclusion_and_all_selection_keeps_landscape(self):
        with tempfile.TemporaryDirectory() as root:
            page=self.page(root);page.drama_input.setPlainText('4100-测试剧');page.create_batch()
            self.assertEqual(page.batch.state['exclude_name'],'小方块')
            page.batch.record_page(page.batch.state['dramas'][0],[{'id':'1','name':'二创-小方块'},{'id':'2','name':'二创-横版'}],1)
            page.refresh_sources();page.set_checked(page.source_table,'all')
            self.assertEqual(page.checked_rows(page.source_table),[1]);self.assertIn('排除',page.source_table.item(0,3).text())
            page.exclude_name.setText('');self.assertTrue(page.apply_name_exclusion())
            page.set_checked(page.source_table,'all');self.assertEqual(page.checked_rows(page.source_table),[0,1])
            self.assertEqual(len(RecreationBatch.load(page.batch.folder).state['sources']),2)

    def test_old_batch_filter_is_not_changed_and_write_failure_keeps_saved_condition(self):
        with tempfile.TemporaryDirectory() as root:
            page=self.page(root);batch=RecreationBatch.create(root,[{'id':'4100','name':'旧批次'}])
            batch.state.pop('exclude_name',None);batch.save();page.batch=batch;page.load_batch_view()
            self.assertEqual(page.exclude_name.text(),'')
            page.exclude_name.setText('小方块')
            with patch('src.recreation.RecreationBatch.save',side_effect=OSError('read only')):
                self.assertFalse(page.apply_name_exclusion())
            self.assertEqual(page.exclude_name.text(),'');self.assertEqual(page.batch.state.get('exclude_name',''),'')
