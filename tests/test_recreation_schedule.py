import tempfile
import unittest
import os
from datetime import datetime
from pathlib import Path
import shutil
from types import SimpleNamespace
from unittest.mock import patch

from src.media import run
from src.micro_presets import RECOMMENDED
from src.recreation import RecreationBatch
from src.recreation_platform import DownloadQueueBlocked
from src.recreation_schedule import ScheduleStore, DownloadHistory, make_schedule, due_window, run_schedule


class ScheduledRecreationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ScheduleStore(self.root)
        self.history = DownloadHistory(self.root)
        self.now = datetime(2026, 11, 23, 18, 30)

    def test_first_run_starts_on_configuration_day_and_missed_days_are_combined(self):
        task = make_schedule('41000000001', '18:00', '小方块', 'download', '', 1, None, self.now)
        self.assertIsNone(due_window(task, self.now.replace(hour=17)))
        self.assertEqual(due_window(task, self.now), ('2026-11-23', '2026-11-23'))
        task['last_day'] = '2026-11-23'
        self.assertEqual(due_window(task, datetime(2026, 11, 26, 9)), ('2026-11-23', '2026-11-25'))
        self.assertIsNone(due_window(task, self.now))

    def test_snapshot_survives_edits_to_the_original_preset(self):
        values = dict(RECOMMENDED, random_ranges={})
        task = make_schedule('41000000001', '18:00', '', 'micro', 'QA', 2, values, self.now)
        values['speed'] = 1.25
        self.store.save(task)
        self.assertEqual(self.store.load()['options']['speed'], RECOMMENDED['speed'])

    def test_incomplete_config_is_rejected_and_preserved_when_rebuilt(self):
        invalid=b'{"schema":1,"enabled":true,"at":"18:00"}'
        self.store.path.write_bytes(invalid)
        with self.assertRaisesRegex(ValueError,'重新设置'):
            self.store.load()
        replacement=make_schedule('41000000001','18:00','','download','',1,None,self.now)
        backup=self.store.rebuild(replacement)
        self.assertEqual(backup.read_bytes(),invalid)
        self.assertEqual(self.store.load(),replacement)

    def test_historical_download_is_skipped_after_old_directory_disappears(self):
        self.history.note('41000000001', '1')
        task = make_schedule('41000000001', '18:00', '', 'download', '', 1, None, self.now)
        batch = RecreationBatch.create(self.root, [{'id': '41000000001', 'name': '测试剧'}])
        def collect(batch, client, *args, **kwargs):
            batch.record_page(batch.state['dramas'][0], [
                {'id': '1', 'name': '旧二创'}, {'id': '2', 'name': '新二创'}], 1)
            batch.state['collection_status'] = 'complete'
            batch.save()
            return {'stopped': False}
        with patch('src.recreation_schedule.collect_platform_materials', side_effect=collect), \
             patch('src.recreation_schedule.download_platform_materials', return_value={'remaining_ids': []}) as download:
            result = run_schedule(task, batch, object(), self.history, due_window(task, self.now), lambda: False)
        self.assertEqual(download.call_args.args[2], ['41000000001_2'])
        self.assertEqual(result['selected'], 1)

    def test_download_failure_leaves_pending_batch_and_later_processes_only_selected_sources(self):
        task = make_schedule('41000000001', '18:00', '', 'md5', 'QA', 1, None, self.now)
        batch = RecreationBatch.create(self.root, [{'id': task['drama'], 'name': '测试剧'}])
        batch.record_page(batch.state['dramas'][0], [{'id': '1', 'name':'测试二创'}], 1)
        batch.state['collection_status'] = 'complete'
        batch.save()
        fixture = self.root/'fixture.mp4'
        run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=size=160x240:rate=15:duration=1',
             '-c:v','libx264',str(fixture)])
        class Client:
            @staticmethod
            def source_url(_):
                return 'fixture'
        window = due_window(task, self.now)
        with patch('src.recreation_platform.download_material', side_effect=DownloadQueueBlocked('连接中断')):
            self.assertFalse(run_schedule(task,batch,Client(),self.history,window,lambda:False)['done'])
        self.assertEqual(self.history.ids(task['drama']),set())
        self.assertEqual(batch.state['outputs'],[])
        with patch('src.recreation_platform.download_material',
                   side_effect=lambda _url,path,**_kw: shutil.copyfile(fixture,path)) as download:
            self.assertTrue(run_schedule(task,batch,Client(),self.history,window,lambda:False)['done'])
            restarted = RecreationBatch.load(batch.folder)
            self.assertTrue(run_schedule(task,restarted,Client(),self.history,window,lambda:False)['done'])
            self.assertEqual(download.call_count,1)
        self.assertEqual(self.history.ids(task['drama']),{'1'})
        self.assertEqual(len(restarted.state['outputs']),1)
        self.assertTrue(Path(restarted.state['outputs'][0]['path']).is_file())

    def test_bad_download_is_deferred_but_healthy_material_is_processed(self):
        task=make_schedule('41000000001','18:00','','md5','QA',1,None,self.now)
        batch=RecreationBatch.create(self.root,[{'id':task['drama'],'name':'测试剧'}])
        batch.record_page(batch.state['dramas'][0],[{'id':'1','name':'好二创'},{'id':'2','name':'坏二创'}],1)
        batch.state['collection_status']='complete'
        batch.save()
        fixture=self.root/'fixture.mp4'
        run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=size=160x240:rate=15:duration=1',
             '-c:v','libx264',str(fixture)])
        def transfer(url,path,**kw):
            if url=='2':
                raise ValueError('该素材已失效')
            shutil.copyfile(fixture,path)
        client=SimpleNamespace(source_url=lambda id:id)
        with patch('src.recreation_platform.download_material',side_effect=transfer):
            result=run_schedule(task,batch,client,self.history,due_window(task,self.now),lambda:False)
        self.assertTrue(result['done'])
        self.assertEqual(result['retry_ids'],['41000000001_2'])
        self.assertEqual([x['source_video_id'] for x in batch.state['outputs']],['41000000001_1'])
        self.assertEqual(self.history.ids(task['drama']),{'1'})
        next_batch=RecreationBatch.create(self.root,[{'id':task['drama'],'name':'测试剧'}])
        next_batch.record_page(next_batch.state['dramas'][0],[{'id':'1','name':'旧二创'},
            {'id':'2','name':'坏二创'},{'id':'3','name':'明天的新二创'}],1)
        next_batch.state['collection_status']='complete'
        next_batch.save()
        with patch('src.recreation_schedule.download_platform_materials',
                   return_value={'remaining_ids':[]}) as downloader:
            run_schedule({**task,'mode':'download'},next_batch,client,self.history,('2026-11-23','2026-11-24'),
                         lambda:False,queued_ids=result['retry_ids'])
        self.assertEqual(downloader.call_args.args[2],['41000000001_3'])

    def test_timer_worker_honors_existing_task_and_registers_micro_output(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop, QTimer
        from PySide6.QtWidgets import QApplication
        from src.recreation_workflow import RecreationWorkflowPage
        app = QApplication.instance() or QApplication([])
        page = RecreationWorkflowPage({'output_root':str(self.root),
            'recreation_preferences_path':str(self.root/'workspace.json')},restore=False)
        self.addCleanup(page.deleteLater)
        owner = page.schedule
        now = datetime.now()
        task = make_schedule('41000000001','00:00','小方块','micro','QA',1,RECOMMENDED,now)
        owner.store.save(task)
        page.external_work_in_progress = lambda: True
        owner.tick()
        self.assertIsNone(owner.store.load()['pending'])
        page.external_work_in_progress = lambda: False
        page.platform.browser = SimpleNamespace(page=lambda:SimpleNamespace(devToolsId=lambda:'test-tab'))
        fixture = self.root/'fixture.mp4'
        run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=size=160x240:rate=15:duration=2',
             '-c:v','libx264',str(fixture)])
        client = SimpleNamespace(ensure_ready=lambda:None, lookup=lambda drama:dict(drama,name='测试剧'),
            fetch_page=lambda _d,word,*a,**kw: {'items':[{'id':'1','name':'新二创'},{'id':'2','name':'坏二创'}] if word=='二创' else [],
                                                'total':2 if word=='二创' else 0,'has_next':False},
            source_url=lambda id:id)
        def transfer(url,path,**kw):
            if url=='2':
                raise ValueError('该素材已失效')
            shutil.copyfile(fixture,path)
        loop=QEventLoop()
        page.task_finished.connect(loop.quit)
        with patch('src.recreation_schedule_ui.find_page_ws_url',return_value='fixture'), \
             patch('src.recreation_schedule_ui.PlatformMaterialClient',return_value=client), \
             patch('src.recreation_platform.download_material',side_effect=transfer):
            owner.tick()
            self.assertTrue(page.work_in_progress())
            owner.tick()
            QTimer.singleShot(15000,loop.quit)
            loop.exec()
            if owner.working:
                owner.stop_on_close()
                owner.worker.wait(15000)
                app.processEvents()
        self.assertFalse(owner.working)
        self.assertEqual(len(page.workspace.folders),1)
        saved = owner.store.load()
        self.assertEqual(saved['last_day'],now.date().isoformat(),saved['status'])
        self.assertIsNone(saved['pending'])
        self.assertEqual(page.workspace.queue[0]['identities'],['41000000001_2'])
        self.assertEqual(due_window(saved,now.replace(hour=23)),None)
        self.assertEqual(len(page.catalog),1)
        self.assertEqual(page.catalog[0]['mode'],'micro')
        self.assertEqual(page.catalog[0]['requested_options']['speed'],RECOMMENDED['speed'])
