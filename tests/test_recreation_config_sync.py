import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from shiboken6 import delete
from src.desktop import MainWindow


class RecreationConfigSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_new_root_applies_to_new_batches_without_moving_current_batch(self):
        with tempfile.TemporaryDirectory() as folder,patch('src.desktop.APP_RUNTIME_ROOT',Path(folder)/'runtime'):
            window=MainWindow(restore=False);page=window.recreation
            page.output_root=Path(folder)/'old';page.preferences_path=Path(folder)/'workspace.json'
            page.drama_input.setPlainText('4100-test');page.create_batch();old=page.batch.folder
            config=dict(window.config,output_root=str(Path(folder)/'new'))
            window.save_settings(config)
            self.assertEqual(page.output_root,Path(folder)/'new')
            self.assertEqual(page.workspace.root,page.output_root)
            self.assertEqual(page.batch.folder,old);self.assertTrue(old.is_dir())
            page.create_batch();self.assertTrue(page.batch.folder.is_relative_to((Path(folder)/'new').resolve()))
            self.assertIn(str(old),page.workspace.folders)
            delete(window);self.app.processEvents()
