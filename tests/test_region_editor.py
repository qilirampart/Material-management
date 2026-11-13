import os
import tempfile
import time
import unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import Qt,QPointF
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication,QWidget,QDialog
from PySide6.QtTest import QTest
from shiboken6 import delete
from src.region_editor import RegionCanvas,RegionEditorDialog
from src.material_variants import VariantOptions
from src.media import run


class RegionEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):self.host=QWidget()

    def tearDown(self):
        self.host.close();delete(self.host);self.app.processEvents()

    def test_letterbox_coordinates_are_relative_to_image_not_widget(self):
        canvas=RegionCanvas(self.host);canvas.resize(400,400)
        canvas.image=QImage(400,200,QImage.Format_RGB32);canvas.image.fill(Qt.gray)
        canvas.show();self.app.processEvents();rect=canvas.image_rect();events=[]
        canvas.rectangle_drawn.connect(events.append)
        start=QPointF(rect.x()+rect.width()*.25,rect.y()+rect.height()*.25).toPoint()
        end=QPointF(rect.x()+rect.width()*.75,rect.y()+rect.height()*.75).toPoint()
        QTest.mousePress(canvas,Qt.LeftButton,pos=start);QTest.mouseMove(canvas,end)
        QTest.mouseRelease(canvas,Qt.LeftButton,pos=end)
        self.assertEqual(len(events),1)
        for key,value in [('x',25),('y',25),('w',50),('h',50)]:self.assertAlmostEqual(events[0][key],value,delta=.6)
        QTest.mouseClick(canvas,Qt.LeftButton,pos=QPointF(2,2).toPoint())
        self.assertEqual(len(events),1)

    def test_real_frame_selection_crop_save_and_cancellation_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.mp4'
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=30:duration=2',
                 '-c:v','libx264',str(source)])
            dialog=RegionEditorDialog(source,VariantOptions(),self.host);dialog.show()
            deadline=time.monotonic()+10
            while dialog.busy and time.monotonic()<deadline:self.app.processEvents();time.sleep(.01)
            self.assertFalse(dialog.busy);self.assertFalse(dialog.canvas.image.isNull(),dialog.status.text())
            dialog.canvas.rectangle_drawn.emit({'x':10,'y':10,'w':20,'h':20})
            dialog.fields['mode'].setCurrentIndex(1)
            self.assertIn('遮挡',dialog.listing.item(0).text())
            self.assertEqual(len(dialog.regions),1)
            dialog.draw_mode.setCurrentIndex(1)
            dialog.canvas.rectangle_drawn.emit({'x':5,'y':10,'w':90,'h':80})
            cache=Path(dialog.cache.name);dialog.accept()
            self.assertEqual(dialog.result(),QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.regions[0]['mode'],'cover')
            self.assertEqual(dialog.edges,{'left':5,'right':5,'top':10,'bottom':10})
            self.assertFalse(cache.exists())
            closing=RegionEditorDialog(source,VariantOptions(),self.host)
            closing.reject()
            deadline=time.monotonic()+10
            while closing.busy and time.monotonic()<deadline:self.app.processEvents();time.sleep(.01)
            self.assertFalse(closing.busy);self.assertFalse(Path(closing.cache.name).exists())
