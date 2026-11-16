import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from shiboken6 import delete
from src.desktop_widgets import PlatformPage


class PlatformFormWaitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_component_loading_retries_but_stops_at_existing_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            page=PlatformPage({'upload_preferences_path':str(Path(folder)/'preferences.json')})
            failed=Mock();page.operation_failed.connect(failed)
            batch={'index':1,'items':[]};generation=page.materials_generation
            with patch('src.desktop_widgets.QTimer.singleShot') as later,patch.object(page,'_run_platform_fill') as fill:
                page._platform_fill_finished(batch,0,{'ok':False,'code':'FORM_API_MISSING','message':'页面多选组件尚未加载'},generation)
                later.assert_called_once()
                failed.assert_not_called()
                later.call_args.args[1]()
                fill.assert_called_once_with(batch,1,generation)
            with patch('src.desktop_widgets.QTimer.singleShot') as later:
                page._platform_fill_finished(batch,5,{'ok':False,'code':'FORM_API_MISSING','message':'页面多选组件尚未加载'},generation)
                later.assert_not_called()
                failed.assert_called_once()
            delete(page);self.app.processEvents()

    def test_changed_batch_does_not_resume_old_fill(self):
        with tempfile.TemporaryDirectory() as folder:
            page=PlatformPage({'upload_preferences_path':str(Path(folder)/'preferences.json')})
            with patch('src.desktop_widgets.QTimer.singleShot') as later:
                page._platform_fill_finished({},0,{'code':'FORM_API_MISSING'},page.materials_generation-1)
                later.assert_not_called()
            delete(page);self.app.processEvents()
