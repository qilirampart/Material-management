import os,tempfile,unittest
import json
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

    def test_only_opted_in_single_lane_pure_download_can_overlap_md5(self):
        self.window.process=Mock()
        self.window.process.state.return_value=QProcess.Running
        page=self.window.recreation
        self.assertTrue(page.md5_start_blocked())
        page.legacy_download_active.set()
        self.window.legacy_download_lanes=1
        self.assertTrue(page.md5_start_blocked())
        page.speed_config['md5_overlap']=True
        self.assertFalse(page.md5_start_blocked())
        self.assertTrue(page.work_in_progress())  # still excludes all other recreation paths
        self.window.legacy_download_lanes=2
        self.assertTrue(page.md5_start_blocked())

    def test_foreground_notice_updates_history_without_scheduling_a_popup(self):
        notices=self.window.notices
        with patch.object(notices,'visible',return_value=True):
            notices.add(2,'改 MD5 完成','完成 3 条',key='same')
        self.assertEqual(len(notices.feed.items),1)
        self.assertFalse(notices.timer.isActive())
        with patch.object(notices,'visible',return_value=False):
            notices.add(2,'改 MD5 完成','完成 3 条',key='same')
            notices.add(3,'微创新结束','完成 1 条',key='away')
        self.assertEqual(list(notices.pending),['away'])
        self.assertIn('1',notices.button.text())
        notices.open(notices.feed.items[0])
        self.assertEqual(self.window.navigation.currentRow(),4)
        self.assertEqual(self.window.recreation.tabs.currentIndex(),3)

    def test_reverse_overlap_only_starts_pure_download_and_uses_one_lane(self):
        window = self.window
        window.config['md5_overlap'] = True
        window.folder = Path(self.temp.name)
        window.input_path = window.folder/'input.xlsx'
        window.recreation.md5.busy = True
        window.recreation.md5.active_budget = {}
        window.download_concurrency.setCurrentIndex(2)
        try:
            with patch('src.desktop.QProcess') as process, patch('src.md5_parallel.resource_issue',return_value=''):
                window.start_batch(['test'], force=True)
                process.assert_not_called()
                window.mode.setCurrentIndex(window.mode.findData('download'))
                window.start_batch(['test'])
                process.return_value.start.assert_called_once()
                request=json.loads(window.request_path.read_text(encoding='utf-8'))
                self.assertEqual(request['operation'],'download')
                self.assertEqual(request['config']['download_concurrency'],1)
                self.assertTrue(window.recreation.legacy_download_active.is_set())
                self.assertEqual(window.recreation.legacy_download_generation,1)
                self.assertEqual(window.download_concurrency.currentData(),3)
        finally:
            window.event_timer.stop()
            window.recreation.md5.busy = False
            if window.batch_lock:
                window.batch_lock.unlock()

    def test_system_notification_coalesces_outcomes_and_prefers_attention(self):
        notices = self.window.notices
        with patch.object(notices, 'visible', return_value=False), \
             patch('src.task_notices.QSystemTrayIcon') as tray:
            notices.add(2, '改 MD5 待处理', '请检查存储空间', attention=True)
            notices.add(3, '微创新本轮结束', '已入库 2 个')
            notices.flush()
            tray.return_value.showMessage.assert_called_once()
            title, detail, *_ = tray.return_value.showMessage.call_args.args
            self.assertIn('另有 1 条', title)
            self.assertEqual(detail, '请检查存储空间')
            self.assertEqual(notices.shown.destination, 2)

    def test_worker_exit_zero_with_a_download_failure_signals_attention_for_this_run(self):
        window = self.window
        window.worker_outcome = 'completed'
        window.batch_task_ids = ['current-ok', 'current-failed']
        window.records = {'current-ok': {'status': 'review_required'},
                          'current-failed': {'status': 'download_failed'},
                          'unrelated': {'status': 'download_failed'}}
        with patch.object(window, 'poll_events'), patch.object(window, 'refresh_table'), \
             patch.object(window.notices, 'add') as notice:
            window.worker_finished(0, QProcess.NormalExit)
        notice.assert_called_once()
        self.assertIn('1 条下载失败', notice.call_args.args[2])
        self.assertTrue(notice.call_args.kwargs['attention'])

    def test_legacy_close_does_not_treat_external_work_as_recreation_work(self):
        self.window.bitrate_task=Mock();self.window.bitrate_task.isRunning.return_value=True
        self.window.bitrate_task.supports_immediate_stop=True
        event=QCloseEvent();self.window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertTrue(self.window.bitrate_stop_event.is_set())
        self.assertFalse(self.window.recreation.collection_stop.is_set())
