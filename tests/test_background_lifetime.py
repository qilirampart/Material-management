import gc,os,unittest,weakref
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QObject,QEvent,QCoreApplication
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from shiboken6 import delete,isValid
from src.ui_design import Background


class Payload:pass


class BackgroundLifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def flush(self):
        for _ in range(3):
            QTest.qWait(5)
            QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
        gc.collect()

    def test_finished_tasks_release_captures_and_native_objects_but_keep_query_safe(self):
        parent=QObject();references=[];results=[];finished=[];tasks=[]
        for index in range(20):
            payload=Payload();payload.data=bytearray(1024*1024);references.append(weakref.ref(payload))
            task=Background(lambda value=payload:len(value.data),parent)
            task.result.connect(results.append);task.finished.connect(lambda:finished.append(True))
            tasks.append(task);task.start();task.wait()
        del payload,task
        self.flush()
        self.assertEqual(len(results),20);self.assertEqual(len(finished),20)
        self.assertTrue(all(ref() is None for ref in references))
        self.assertEqual(parent.findChildren(Background),[])
        self.assertTrue(all(not task.isRunning() for task in tasks))
        for task in tasks:task.deleteLater()  # Legacy callers may clean up again.
        delete(parent)

    def test_task_is_not_destroyed_before_result_and_finished_callbacks(self):
        parent=QObject();events=[];task=Background(lambda:42,parent)
        task.result.connect(lambda value:events.append(('result',value,isValid(task))))
        task.finished.connect(lambda:events.append(('finished',isValid(task))))
        task.start()
        for _ in range(100):
            QTest.qWait(5)
            if len(events)==2:break
        self.assertEqual(events,[('result',42,True),('finished',True)])
        self.flush();self.assertFalse(isValid(task));delete(parent)
