import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from shiboken6 import delete
from src.recreation import RecreationBatch
from src.recreation_workspace import RecreationWorkspace
from src.recreation_workflow import RecreationWorkflowPage


class RecreationResourcePerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_resolve_uses_one_index_per_batch_and_keeps_input_order(self):
        with tempfile.TemporaryDirectory() as folder:
            batch=RecreationBatch(Path(folder)/'batch',{'sources':[{'video_id':str(i),'path':''} for i in range(1000)]})
            workspace=RecreationWorkspace(Path(folder)/'unused.json',folder)
            workspace.inputs['micro']=[{'folder':str(batch.folder),'video_id':str(i)} for i in reversed(range(1000))]
            with patch('src.recreation_workspace.RecreationBatch.load',return_value=batch) as load,patch.object(batch,'source_by_id',side_effect=AssertionError('linear lookup')):
                result=workspace.resolve_inputs('micro')
            load.assert_called_once();self.assertEqual([x['video_id'] for x in result],[str(i) for i in reversed(range(1000))])
            workspace.inputs['micro'].append({'folder':str(batch.folder),'video_id':'missing'})
            with patch('src.recreation_workspace.RecreationBatch.load',return_value=batch),self.assertRaises(StopIteration):workspace.resolve_inputs('micro')

    def test_incremental_refresh_reuses_cells_and_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            page=RecreationWorkflowPage({'output_root':folder,'recreation_preferences_path':str(Path(folder)/'prefs.json')},restore=False)
            sources=[{'video_id':str(i),'drama':'test','name':'test','path':'','download_status':'pending'} for i in range(200)]
            page.batch=RecreationBatch(Path(folder)/'batch',{'sources':sources,'outputs':[]})
            page.resize(1200,760);page.show();page.refresh_sources();self.app.processEvents();table=page.source_table
            old=table.item(0,1);table.item(0,0).setCheckState(Qt.Checked);table.setCurrentCell(0,1)
            table.verticalScrollBar().setValue(80);scroll=table.verticalScrollBar().value()
            sources[1]['download_status']='failed';sources[1]['download_error']='network'
            sources.append({'video_id':'new','drama':'test','name':'new','path':'','download_status':'pending'})
            page.refresh_sources(incremental=True)
            self.assertIs(table.item(0,1),old);self.assertEqual(table.item(0,0).checkState(),Qt.Checked)
            self.assertEqual(table.currentRow(),0);self.assertEqual(table.item(1,3).text(),'下载失败')
            self.assertGreater(scroll,0);self.assertEqual(table.verticalScrollBar().value(),scroll)
            self.assertEqual(table.item(1,3).toolTip(),'network');self.assertEqual(table.rowCount(),201)
            sources[0]['path']='unreadable.mp4'
            with patch('src.recreation_page.Path.is_file',side_effect=PermissionError('denied')),self.assertRaises(PermissionError):
                page.refresh_sources()
            self.assertTrue(table.updatesEnabled());self.assertFalse(table.signalsBlocked())
            delete(page);self.app.processEvents()
