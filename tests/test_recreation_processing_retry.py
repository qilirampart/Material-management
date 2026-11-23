import os
import tempfile
import time
import unittest
from pathlib import Path
from shutil import copyfile
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from src.media import run
from src.recreation import RecreationBatch
from src.recreation_workflow import RecreationWorkflowPage


class ProcessingRetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def fixture(self, root):
        page = RecreationWorkflowPage({'output_root': str(root),
            'recreation_preferences_path': str(root/'prefs.json')}, restore=False)
        batch = page.workspace.create('4100-测试剧')[0]
        good = root/'first.mp4'
        run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i',
             'testsrc2=size=160x240:rate=15:duration=1', '-c:v', 'libx264', str(good)])
        bad, third = root/'second.mp4', root/'third.mp4'
        bad.write_bytes(b'bad input')
        copyfile(good, third)
        batch.add_local_sources([str(good), str(bad), str(third)], batch.state['dramas'][0])
        page.workspace.add_inputs('md5', batch.folder, [i['video_id'] for i in batch.state['sources']])
        page.md5.uploader.setText('TEST')
        page.md5.refresh()
        page.set_checked(page.md5.table, 'all')
        return page, batch, good, bad

    def wait(self, panel):
        until = time.monotonic()+10
        while panel.busy and time.monotonic()<until:
            self.app.processEvents()
            time.sleep(.01)
        self.assertFalse(panel.busy)

    def test_failed_middle_item_is_the_only_input_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            page, batch, good, bad = self.fixture(Path(folder))
            panel = page.md5
            panel.start()
            self.wait(panel)
            self.assertEqual(len(RecreationBatch.load(batch.folder).state['outputs']), 2)
            self.assertEqual([(x['name'], x['stage'], x['version']) for x in panel.failures],
                             [(bad.name, '读取原片', 1)])
            self.assertTrue(panel.failure_button.isEnabled())
            self.assertTrue(panel.retry_button.isEnabled())
            self.assertIn('1 版失败', panel.table.item(1, 3).text())
            self.assertIn('MP4 文件不完整', panel.table.item(1, 3).toolTip())
            copyfile(good, bad)
            panel.count.setValue(3)  # retry uses the original options, not the edited count
            panel.retry_button.click()
            self.wait(panel)
            outputs = RecreationBatch.load(batch.folder).state['outputs']
            self.assertEqual(len(outputs), 3)
            self.assertEqual([x['version'] for x in outputs if Path(x['source_path']) == bad], [1])
            self.assertEqual(panel.failures, [])
            self.assertFalse(panel.retry_button.isEnabled())
            page.close()

    def test_outputs_with_record_save_failure_are_not_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            page, batch, good, bad = self.fixture(Path(folder))
            panel = page.md5
            for row in range(panel.table.rowCount()):
                panel.table.item(row, 0).setCheckState(
                    Qt.Checked if panel.items[row]['path'] == str(good) else Qt.Unchecked)
            with patch.object(RecreationBatch, 'add_outputs', side_effect=OSError('write failed')):
                panel.start()
                self.wait(panel)
            self.assertEqual(len(panel.failures), 1)
            self.assertEqual(panel.failures[0]['stage'], '保存批次')
            self.assertIn('找回加工成品', panel.failures[0]['error'])
            self.assertTrue(Path(panel.failures[0]['manifest']).is_file())
            self.assertEqual(len(list((batch.folder/'加工成品').rglob('*.mp4'))), 1)
            self.assertTrue(panel.failure_button.isEnabled())
            self.assertFalse(panel.retry_button.isEnabled())
            page.close()
