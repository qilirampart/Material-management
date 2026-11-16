import os,tempfile,unittest
from unittest.mock import Mock,patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication,QWidget
from shiboken6 import delete
from src.recreation_page import RecreationPage

class CollectionRestartStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_restarted_download_does_not_keep_previous_stopped_summary(self):
        host=QWidget()
        with tempfile.TemporaryDirectory() as folder:
            page=RecreationPage({'output_root':folder},restore=False);page.setParent(host)
            page.drama_input.setPlainText('4100-测试剧');page.create_batch()
            page.message.setText('完成 0 条 · 已停止')
            page.platform.browser=Mock();page.platform.browser.page.return_value.devToolsId.return_value='test'
            with patch('src.recreation_page.Background'):
                page._start_browser_task('download',identities=[])
            self.assertNotIn('已停止',page.message.text())
            self.assertIn('正在连接',page.collection_status.text())
            page.collection_task=None;page._set_collection_busy(False)
        host.close();delete(host);self.app.processEvents()
