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

    def test_manual_filters_save_per_batch_and_only_matching_rows_are_selected(self):
        with tempfile.TemporaryDirectory() as root:
            page=self.page(root);page.drama_input.setPlainText('4100-测试剧');page.create_batch()
            drama=page.batch.state['dramas'][0]
            page.batch.record_page(drama,[{'id':'1','name':'高光'},
                {'id':'2','name':'口播-旧版'},{'id':'3','name':'二创'},{'id':'4','name':'口播'}],1)
            page.include_name.setText('高光，口播')
            page.exclude_name.setText('旧版；小方块')
            self.assertTrue(page.apply_name_exclusion())
            page.set_checked(page.source_table,'all')
            self.assertEqual(page.checked_rows(page.source_table),[0,3])
            self.assertIn('未命中',page.source_table.item(2,3).text())
            page.batch=RecreationBatch.load(page.batch.folder)
            page.load_batch_view()
            self.assertEqual(page.include_name.text(),'高光, 口播')
            self.assertEqual(page.exclude_name.text(),'旧版, 小方块')
            with patch.object(page,'_start_browser_task') as start:
                page.start_downloads(False)
            start.assert_called_once_with('download',identities=['4100_1','4100_4'])
