import os,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QProcess
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication
from shiboken6 import delete
from src.desktop import MainWindow


class ResourceCoordinationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.patch=patch('src.desktop.APP_RUNTIME_ROOT',Path(self.temp.name));self.patch.start()
        self.window=MainWindow(restore=False)
    def tearDown(self):
        self.window.process=None;self.window.bitrate_task=None
        self.window.recreation.collection_busy=False;self.window.close_after=False
        delete(self.window);self.app.processEvents();self.patch.stop();self.temp.cleanup()

    def test_legacy_process_blocks_recreation_starts_without_disabling_browsing(self):
        self.window.process=Mock();self.window.process.state.return_value=QProcess.Running
        page=self.window.recreation
        self.assertTrue(page.work_in_progress())
        self.assertFalse(page.own_work_in_progress())
        self.assertTrue(page.isEnabled())
        with patch.object(page,'create_batch') as create,patch.object(page,'continue_upload') as upload,patch('src.recreation_processing.Background') as task:
            page.query_materials();page.micro.start();page.begin_upload()
            create.assert_not_called();upload.assert_not_called();task.assert_not_called()

    def test_pending_recreation_callback_also_blocks_legacy_start(self):
        self.window.recreation.collection_busy=True
        with patch('src.desktop.QMessageBox.information') as info:
            self.window.start_batch()
        info.assert_not_called();self.assertIsNone(self.window.process)

    def test_lightweight_update_check_does_not_block_recreation(self):
        self.window.settings.update_check_task=Mock()
        self.window.settings.update_check_task.isRunning.return_value=True
        self.assertFalse(self.window.recreation.work_in_progress())

    def test_legacy_close_does_not_treat_external_work_as_recreation_work(self):
        self.window.bitrate_task=Mock();self.window.bitrate_task.isRunning.return_value=True
        self.window.bitrate_task.supports_immediate_stop=True
        event=QCloseEvent();self.window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertTrue(self.window.bitrate_stop_event.is_set())
        self.assertFalse(self.window.recreation.collection_stop.is_set())
