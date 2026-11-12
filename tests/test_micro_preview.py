import os
import unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from src.micro_preview import MicroPreviewDialog


class MicroPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_fullscreen_can_exit_without_closing_preview(self):
        dialog=MicroPreviewDialog({'path':'','clip_start':0,
            'metadata':{'duration':10,'width':720,'height':1280}})
        dialog.show()
        dialog.activateWindow()
        self.app.processEvents()
        QTest.mouseDClick(dialog.video,Qt.LeftButton)
        self.app.processEvents()
        self.assertTrue(dialog.isFullScreen())
        QTest.keyClick(dialog,Qt.Key_Escape)
        self.app.processEvents()
        self.assertFalse(dialog.isFullScreen())
        self.assertIsNotNone(dialog.player)
        self.assertTrue(dialog.isVisible())
        QTest.keyClick(dialog,Qt.Key_F11)
        self.app.processEvents()
        self.assertTrue(dialog.isFullScreen())
        QTest.keyClick(dialog,Qt.Key_F11)
        self.app.processEvents()
        self.assertFalse(dialog.isFullScreen())
        dialog.reject()
        self.assertIsNone(dialog.player)
