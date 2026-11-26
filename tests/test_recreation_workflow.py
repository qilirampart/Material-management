import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from src.recreation_workflow import RecreationWorkflowPage
from src.recreation import RecreationBatch
from src.media import run


class WorkflowTests(unittest.TestCase):
    def test_queue_keeps_failed_id_for_next_resume_without_blocking_other_batches(self):
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            first, second = page.workspace.create('4100-第一剧\n4200-第二剧')
            for batch, ids in ((first, ['1','2']), (second, ['1'])):
                drama = batch.state['dramas'][0]
                batch.record_page(drama, [{'id': x,'name': x} for x in ids], 1)
                page.workspace.enqueue(batch.folder, [f"{drama['id']}_{x}" for x in ids])
            def start(*args, **kwargs):
                page._set_collection_busy(True)
            with patch.object(page,'_start_browser_task', side_effect=start) as worker:
                page.resume_download_queue()
                page.collection_result({'completed':1,'failed':1,'skipped':0,'stopped':False,
                                        'remaining_ids':['4100_2']})
                page.collection_finished()
                self.app.processEvents()
                self.assertEqual(page.batch.folder, second.folder)
                page.collection_result({'completed':1,'failed':0,'skipped':0,'stopped':False,'remaining_ids':[]})
                page.collection_finished()
                self.app.processEvents()
                self.assertFalse(page.queue_running)
                stored = type(page.workspace)(page.workspace.path, folder)
                self.assertEqual(stored.queue, [{'folder':str(first.folder),'identities':['4100_2']}])
                page.resume_download_queue()
                worker.assert_called_with('download', identities=['4100_2'])
                page.stop_collection()
                page.collection_finished()
            page.close()

    def test_queue_save_failure_restores_the_active_job(self):
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            batch = page.workspace.create('4100-测试剧')[0]
            page.workspace.enqueue(batch.folder, ['4100_1'])
            with patch.object(page,'_start_browser_task', side_effect=lambda *a,**kw: page._set_collection_busy(True)):
                page.resume_download_queue()
            before = list(page.workspace.queue)
            page.collection_result({'completed':1,'failed':0,'skipped':0,'stopped':False,'remaining_ids':[]})
            with patch.object(page.workspace,'save', side_effect=OSError):
                page.collection_finished()
            self.assertEqual(page.workspace.queue, before)
            self.assertFalse(page.queue_running)
            self.assertIn('保存失败', page.message.text())
            page.close()

    def test_blocked_queue_keeps_current_position_and_independent_pending_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            first, second = page.workspace.create('4100-第一剧\n4200-第二剧')
            page.workspace.enqueue(first.folder, ['4100_1','4100_2'])
            page.workspace.enqueue(second.folder, ['4200_1'])
            with patch.object(page,'_start_browser_task', side_effect=lambda *a,**kw: page._set_collection_busy(True)) as worker:
                page.resume_download_queue()
                page.collection_result({'completed':1,'failed':1,'skipped':0,'stopped':False,
                                        'remaining_ids':['4100_2'], 'pause_reason':'智投登录已失效'})
                page.collection_finished()
                self.app.processEvents()
                worker.assert_called_once()
            self.assertFalse(page.queue_running)
            self.assertIn('登录已失效', page.collection_status.text())
            self.assertEqual(page.collection_bar.format(), '下载队列已暂停')
            self.assertEqual([j['identities'] for j in page.workspace.queue], [['4100_2'], ['4200_1']])
            self.assertIn('2 批 / 2 条', page.queue_summary.text())
            page.close()

    def test_recreation_director_precedence_and_default_survives_restart(self):
        from src.upload import load_upload_preferences, remember_upload_preferences
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            path = Path(folder) / 'upload-prefs.json'
            page.platform.preferences_path = path
            remember_upload_preferences(path, drama_name='一剧', drama_platform_id='4100',
                                        director='专属编导', uploader_initials='TEST')
            page.platform.upload_preferences = load_upload_preferences(path)
            with patch('src.recreation_workflow.QInputDialog.getText', return_value=('默认编导', True)):
                page.edit_default_director()
            stored = load_upload_preferences(path)
            self.assertEqual(stored['default_director'], '默认编导')
            page.platform.upload_preferences = stored
            self.assertEqual(page.resolve_upload_director('一剧', '4100'), '专属编导')
            self.assertEqual(page.resolve_upload_director('一剧', '4200'), '默认编导')
            page.upload_director.setText('本轮编导')
            self.assertEqual(page.resolve_upload_director('一剧', '4100'), '本轮编导')
            with patch('src.recreation_workflow.QInputDialog.getText', return_value=('', True)):
                page.edit_default_director()
            self.assertEqual(load_upload_preferences(path)['default_director'], '')
            self.assertEqual(load_upload_preferences(path)['dramas']['一剧']['ids']['4100']['director'], '专属编导')
            page.close()

    def test_batch_filter_preserves_checks_and_current_batch_but_scopes_actions(self):
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            first, second = page.workspace.create('4100-同名剧\n4200-同名剧')
            page.refresh_batch_list()
            page.batch_list.setCurrentRow(0)
            for row in range(2):
                page.batch_list.item(row).setCheckState(Qt.Checked)
            page.batch_search.setText('4200')
            self.assertEqual(page.batch.folder, first.folder)
            self.assertEqual(page.checked_batch_folders(), [str(second.folder)])
            page.batch_search.clear()
            self.assertEqual(page.checked_batch_folders(), [str(first.folder), str(second.folder)])
            self.assertEqual(page.batch_list.currentRow(), 0)
            page.close()

    def test_local_only_import_never_downloads_missing_items_or_adds_unchecked_items(self):
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            batch = page.workspace.create('4100-测试剧')[0]
            batch.record_page(batch.state['dramas'][0], [{'id':str(i),'name':str(i)} for i in range(1,4)], 1)
            path = Path(folder)/'ready.mp4'
            path.write_bytes(b'video')
            for i in (0, 2):
                batch.state['sources'][i].update(path=str(path), download_status='downloaded')
            batch.save()
            with patch.object(page, '_start_browser_task') as start:
                for mode in ('md5', 'micro'):
                    page.request_processing_import(mode, str(batch.folder), ['4100_1','4100_2'], local_only=True)
                    self.assertEqual([x['video_id'] for x in page.workspace.inputs[mode]], ['4100_1'])
                    self.assertIn('跳过 1 条', page.message.text())
                start.assert_not_called()
            page.close()

    def test_active_upload_queue_cannot_be_rebuilt_with_stale_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            page.upload_groups = [{'drama': '既有批次', 'outputs': []}]
            page.begin_upload()
            self.assertIn('当前队列', page.message.text())
            self.assertEqual(page.upload_groups[0]['drama'], '既有批次')
            page.close()

    def test_upload_does_not_advance_when_success_cannot_be_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            group = {'folder': folder, 'drama_id': '4100', 'drama': '测试剧', 'outputs': []}
            page.current_upload = group
            page.upload_groups = [group]
            with patch('src.recreation_workflow.record_upload', side_effect=OSError('disk')):
                page.upload_completed({'uploaded': 1, 'stopped': False})
            self.assertEqual(page.upload_groups, [group])
            self.assertFalse(page.next_upload_button.isEnabled())
            page.close()

    def test_101_distinct_files_advance_once_and_display_exact_queue_snapshot(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            batch = page.workspace.create('4100-测试剧')[0]
            products = []
            for i in range(101):
                path = batch.folder / '加工成品' / 'run123' / '测试剧' / '改md5' / f'{i:03d}.mp4'
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'video')
                products.append({'path': str(path), 'drama': '测试剧', 'mode': 'md5', 'metadata': {},
                                 'upload_drama_info': {'drama_platform_id': '4100', 'drama_name': '测试剧'}})
            batch.add_outputs(products)
            page.refresh_outputs()
            page.output_search.setText('run123')
            page.set_checked(page.output_table, 'all')
            page.upload_director.setText('编导')
            page.platform.uploader_initials.setText('TEST')
            page.begin_upload()
            page.platform.browser = Mock()
            page.platform.browser.page.return_value.devToolsId.return_value = 'target'
            actual = []
            def stage():
                group = page.current_upload
                items = [{'original_path': item['path'], 'upload_name': Path(item['path']).name}
                         for item in group['outputs']]
                page.platform.upload_batches = [{'items': items}]
                page.files_for_upload_ready({})
                page.files_for_upload_ready({})  # duplicate readiness must not send another upload
                return True
            def send(ws, names, drama_id, **kwargs):
                actual.append(list(names))
                return {'uploaded': len(names), 'stopped': False}
            with patch('src.recreation_workflow.find_page_ws_url', return_value='ws://test'), \
                    patch('src.recreation_workflow.evaluate_edge_page', return_value={'no_form': True}), \
                    patch.object(page.platform, 'prepare_upload', side_effect=stage), \
                    patch('src.recreation_workflow.upload_files', side_effect=send):
                for number, size in enumerate((50, 50, 1), 1):
                    self.assertIn(f'第 {number} / 3 批', page.upload_batch_summary.text())
                    shown = [page.upload_batch_files.item(i).text() for i in range(size)]
                    self.assertFalse(page.auto_button.isEnabled())
                    page.continue_upload()
                    page.continue_upload()
                    deadline = time.monotonic() + 5
                    while page.work_in_progress() and time.monotonic() < deadline:
                        self.app.processEvents()
                        time.sleep(.005)
                    self.assertFalse(page.work_in_progress())
                    self.assertEqual(actual[-1], shown)
            self.assertEqual([x for group in actual for x in group], [f'{i:03d}.mp4' for i in range(101)])
            self.assertEqual(page.output_table.rowCount(), 0)
            self.assertEqual(len(RecreationBatch.load(batch.folder).state['uploads']), 3)
            page.platform.browser = None
            page.close()

    def test_auto_submit_only_advances_after_receipt_is_saved_and_form_closes(self):
        from unittest.mock import Mock
        from PySide6.QtWidgets import QMessageBox
        from src.recreation_platform import RecreationPlatformError

        for first_result in ('confirmed','uncertain','close_failed','save_failed'):
            with self.subTest(first_result=first_result), tempfile.TemporaryDirectory() as folder:
                page=self.page(folder)
                batch=page.workspace.create('4100-测试剧')[0]
                products=[]
                for i in range(51):
                    p=batch.folder/f'{i:02d}.mp4'
                    p.write_bytes(b'video')
                    products.append({'path':str(p),'drama':'测试剧','mode':'md5','metadata':{},
                        'upload_drama_info':{'drama_platform_id':'4100','drama_name':'测试剧'}})
                batch.add_outputs(products)
                page.refresh_outputs()
                page.set_checked(page.output_table,'all')
                page.upload_director.setText('编导')
                page.platform.uploader_initials.setText('TEST')
                self.assertEqual(page.submit_mode.currentData(),'manual')
                page.submit_mode.setCurrentIndex(1)
                with patch.object(QMessageBox,'exec',return_value=QMessageBox.No):
                    page.begin_upload()
                self.assertFalse(page.upload_groups)
                with patch.object(QMessageBox,'exec',return_value=QMessageBox.Yes):
                    page.begin_upload()
                self.assertFalse(page.submit_mode.isEnabled())
                self.assertEqual([len(g['outputs']) for g in page.upload_groups],[50,1])
                page.platform.browser=Mock()
                page.task_notice=Mock()
                page.platform.browser.page.return_value.devToolsId.return_value='target'
                attempts=[]
                transfers=[]
                def entries():
                    return RecreationBatch.load(batch.folder).state['uploads']
                def stage():
                    page.platform.upload_batches=[{'items':[{'original_path':item['path'],
                        'upload_name':Path(item['path']).name} for item in page.current_upload['outputs']]}]
                    page.files_for_upload_ready({})
                    page.files_for_upload_ready({})
                    return True
                def send(ws,names,drama_id,**kw):
                    transfers.append(list(names))
                    if len(transfers)==2:
                        self.assertEqual(entries()[0]['status'],'submitted')
                    return {'uploaded':len(names),'failed':0,'stopped':False}
                def submit(ws,attempt,names,drama,director,**kw):
                    self.assertEqual(entries()[-1]['status'],'submission_review')
                    attempts.append(list(names))
                    if first_result=='uncertain':
                        raise RecreationPlatformError('提交结果待核对')
                    return [str(5000+int(Path(n).stem)) for n in names]
                from src.recreation_upload import record_upload as save_record
                def record(group,attempt,status,*a,**kw):
                    if first_result=='save_failed' and status=='submitted':
                        raise OSError('disk')
                    return save_record(group,attempt,status,*a,**kw)
                with patch('src.recreation_workflow.find_page_ws_url',return_value='ws://test'), \
                     patch('src.recreation_workflow.evaluate_edge_page',return_value={'no_form':True}), \
                     patch.object(page.platform,'prepare_upload',side_effect=stage), \
                     patch('src.recreation_workflow.upload_files',side_effect=send), \
                     patch('src.recreation_workflow.record_upload',side_effect=record), \
                     patch('src.recreation_workflow.submit_uploaded_batch',side_effect=submit), \
                     patch('src.recreation_workflow.close_submission_receipt',return_value=first_result!='close_failed'):
                    page.continue_upload()
                    page.continue_upload()
                    deadline=time.monotonic()+5
                    while time.monotonic()<deadline and (page.work_in_progress() or
                          (first_result=='confirmed' and len(attempts)<2)):
                        self.app.processEvents()
                        time.sleep(.005)
                    self.app.processEvents()
                self.assertEqual(len(attempts),2 if first_result=='confirmed' else 1)
                self.assertEqual(transfers,attempts)
                if first_result=='confirmed':
                    self.assertEqual(page.task_notice.call_count,1)
                    self.assertIn('51 条',page.task_notice.call_args.args[2])
                    self.assertEqual([x['uploaded'] for x in entries()],[50,1])
                    self.assertTrue(all(x['submitted'] for x in entries()))
                    self.assertEqual(page.submit_mode.currentData(),'manual')
                    self.assertFalse(page.upload_groups)
                elif first_result=='close_failed':
                    self.assertTrue(entries()[0]['submitted'])
                    self.assertEqual([g['number'] for g in page.upload_groups],[2])
                else:
                    self.assertEqual(entries()[0]['status'],'submission_review')
                    self.assertFalse(page.next_upload_button.isEnabled())
                page.platform.browser=None
                page.close()

    def test_auto_handoff_keeps_ticket_when_busy_then_starts_once(self):
        with tempfile.TemporaryDirectory() as folder:
            page=self.page(folder)
            current={'outputs':[],'drama':'测试','number':2,'auto_submit':True}
            page.upload_groups=[current]
            page.auto_continue_group=current
            page.external_work_in_progress=lambda:True
            with patch.object(page,'continue_upload') as start:
                page.upload_transfer_finished()
                self.app.processEvents()
                self.assertIs(page.auto_continue_group,current)
                self.assertIn('等待',page.upload_status.text())
                start.assert_not_called()
                page.external_work_in_progress=lambda:False
                page.resume_auto_upload()
                page.resume_auto_upload()
                start.assert_called_once()
            page.close()

    def test_new_upload_queue_keeps_sequence_after_restart_and_reads_old_records(self):
        from datetime import date
        from src.recreation_upload import record_upload
        with tempfile.TemporaryDirectory() as folder:
            page=self.page(folder)
            batch=page.workspace.create('4100-测试剧')[0]
            stored={'folder':str(batch.folder),'drama_id':'4100','outputs':[{'path':'old'}]}
            record_upload(stored,'old','uploaded',1,names=[f'APP-繁花-王俨-改md5-测试剧-QA-{date.today():%y%m%d}-09.mp4'])
            path=batch.folder/'new.mp4'
            path.write_bytes(b'test')
            batch=RecreationBatch.load(batch.folder)
            batch.add_outputs([{'path':str(path),'mode':'md5','metadata':{},'drama':'测试剧',
                'upload_drama_info':{'drama_platform_id':'4100','drama_name':'测试剧'}}])
            for expected in (10,11):
                page.workspace.folders=[str(batch.folder)]
                page.refresh_outputs()
                page.set_checked(page.output_table,'all')
                page.upload_director.setText('编导')
                page.platform.uploader_initials.setText('QA')
                page.begin_upload()
                self.assertEqual(page.upload_groups[0]['sequence_start'],expected)
                self.assertEqual(page.upload_groups[0]['upload_date'],date.today())
                page.close()
                page=self.page(folder)
            page.close()

    def test_uncertain_upload_is_not_retried_after_restart(self):
        from src.recreation_upload import record_upload
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            batch = page.workspace.create('4100-测试剧')[0]
            path = batch.folder / 'ready.mp4'
            path.write_bytes(b'video')
            item = {'path': str(path), 'drama': '测试剧', 'mode': 'md5', 'metadata': {},
                    'upload_drama_info': {'drama_platform_id': '4100', 'drama_name': '测试剧'}}
            batch.add_outputs([item])
            group = {'folder': str(batch.folder), 'drama_id': '4100', 'drama': '测试剧', 'outputs': [item]}
            record_upload(group, 'attempt-a', 'review')
            page.upload_groups, page.current_upload = [group], group
            page.upload_busy, page.upload_attempt = True, 'attempt-a'
            page.upload_failed('测试断开')
            self.assertFalse(page.next_upload_button.isEnabled())
            self.assertFalse(page.auto_button.isEnabled())
            page.close()
            reopened = RecreationWorkflowPage({'output_root': folder,
                'recreation_preferences_path': str(Path(folder) / 'prefs.json')}, restore=True)
            self.assertEqual(reopened.output_table.rowCount(), 0)
            reopened.output_state.setCurrentIndex(reopened.output_state.findData('review'))
            reopened.set_checked(reopened.output_table, 'all')
            self.assertEqual(reopened.output_table.rowCount(), 1)
            reopened.begin_upload()
            self.assertFalse(reopened.upload_groups)
            self.assertIn('不能直接重传', reopened.message.text())
            reopened.close()

    def test_local_import_uses_dialog_batch_not_current_download_batch(self):
        from PySide6.QtWidgets import QDialog
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            page.drama_input.setPlainText('4100-第一剧\n4200-第二剧')
            page.create_batch()
            other = page.workspace.folders[1]
            source = Path(folder) / 'local.mp4'
            source.write_bytes(b'video')
            with patch('src.recreation_workflow.QFileDialog.getOpenFileNames', return_value=([str(source)], '')):
                page.import_processing_local('md5', QDialog(page), other)
            self.assertEqual(page.md5.items[0]['drama_id'], '4200')
            self.assertEqual(RecreationBatch.load(page.workspace.folders[0]).state['sources'], [])
            page.close()
    def test_changed_workspace_paths_are_respected_before_creating_or_remembering_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            original_root = Path(folder) / 'original'
            original_root.mkdir()
            page = self.page(str(original_root))
            new_root = Path(folder) / 'new'
            page.output_root = new_root
            page.preferences_path = new_root / 'prefs.json'
            page.drama_input.setPlainText('4100-测试剧')
            page.create_batch()
            self.assertTrue(page.batch.folder.is_relative_to(new_root.resolve()))
            self.assertTrue(page.preferences_path.is_file())
            self.assertFalse((original_root / 'prefs.json').exists())
            self.assertEqual(page.workspace.path, page.preferences_path)
            page.close()
    def test_successful_upload_is_durable_and_duplicate_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            page.drama_input.setPlainText('4100-测试剧')
            page.create_batch()
            path = Path(folder) / 'ready.mp4'
            path.write_bytes(b'video')
            output = {'path': str(path), 'drama': '测试剧', 'mode': 'md5', 'metadata': {},
                      'upload_drama_info': {'drama_platform_id': '4100', 'drama_name': '测试剧'}}
            page.batch.add_outputs([output])
            group = {'folder': str(page.batch.folder), 'drama_id': '4100', 'drama': '测试剧', 'outputs': [output]}
            page.current_upload, page.upload_groups = group, [group]
            page.upload_completed({'uploaded': 1, 'stopped': False})
            self.assertEqual(RecreationBatch.load(page.batch.folder).state['uploads'][0]['submitted'], False)
            self.assertEqual(page.catalog, [])
            page.output_state.setCurrentIndex(page.output_state.findData('uploaded'))
            self.assertTrue(page.catalog[0]['uploaded_before'])
            page.set_checked(page.output_table, 'all')
            with patch('src.recreation_workflow.QMessageBox.question', return_value=QMessageBox.No) as ask:
                page.begin_upload()
                ask.assert_called_once()
                self.assertFalse(page.upload_groups)
            page.close()

    def test_download_queue_pauses_durably_and_advances_between_independent_batches(self):
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            batches = page.workspace.create('4100-第一剧\n4200-第二剧')
            for batch in batches:
                batch.record_page(batch.state['dramas'][0], [{'id': '1', 'name': '二创'}], 1)
                page.workspace.enqueue(batch.folder, [batch.state['dramas'][0]['id'] + '_1'])
            def start(*args, **kwargs):
                page._set_collection_busy(True)
            with patch.object(page, '_start_browser_task', side_effect=start) as worker:
                page.resume_download_queue()
                self.assertEqual(page.batch.state['dramas'][0]['id'], '4100')
                page.stop_collection()
                page.collection_result({'completed': 0, 'failed': 0, 'skipped': 0, 'stopped': True})
                page.collection_finished()
                self.assertEqual(len(page.workspace.queue), 2)
                self.assertFalse(page.queue_running)
                page.resume_download_queue()
                page.collection_result({'completed': 1, 'failed': 0, 'skipped': 0, 'stopped': False})
                page.collection_finished()
                self.app.processEvents()
                self.assertEqual(page.batch.state['dramas'][0]['id'], '4200')
                self.assertEqual(len(page.workspace.queue), 1)
                page.collection_failed('测试中断')
                page.collection_finished()
                self.assertFalse(page.queue_running)
                self.assertEqual(worker.call_count, 3)
            page.close()

    def test_upload_preflight_refuses_unsaved_form_before_any_file_selection(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            page.platform.browser = Mock()
            page.platform.browser.page.return_value.devToolsId.return_value = 'target'
            page.upload_groups = [{'folder': folder, 'drama_id': '4100', 'drama': '测试剧', 'outputs': []}]
            with patch('src.recreation_workflow.find_page_ws_url', return_value='ws://test'), \
                 patch('src.recreation_workflow.evaluate_edge_page', return_value={'unsaved': True}), \
                 patch.object(page.platform, 'fill_platform_form') as fill:
                page.continue_upload()
                deadline = time.monotonic()+5
                while page.upload_busy and time.monotonic()<deadline:
                    self.app.processEvents()
                    time.sleep(.01)
                self.assertFalse(page.upload_busy)
                self.assertIn('不会覆盖', page.message.text())
                fill.assert_not_called()
            page.platform.browser = None
            page.close()

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def page(self, folder):
        return RecreationWorkflowPage({'output_root': folder, 'recreation_preferences_path': str(Path(folder) / 'prefs.json')}, restore=False)

    def test_six_stages_share_one_platform_component_and_separate_batches(self):
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            self.assertEqual(page.tabs.count(), 6)
            page.drama_input.setPlainText('4100-第一剧\n4200-第二剧')
            page.create_batch()
            self.assertEqual(page.batch_list.count(), 2)
            page.show()
            page.tabs.setCurrentIndex(1)
            self.app.processEvents()
            self.assertTrue(page.source_table.isVisible())
            self.assertEqual(len(page.batch.state['dramas']), 1)
            page.batch_list.setCurrentRow(1)
            self.assertEqual(page.batch.state['dramas'][0]['id'], '4200')
            self.assertIs(page.platform.browser_card.parentWidget(), page.tabs.widget(0))
            self.assertEqual(page.platform.upload_departments, ['客户端二组'])
            page.close()

    def test_pending_source_requires_consent_and_only_successful_downloads_are_imported(self):
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            page.drama_input.setPlainText('4100-测试剧')
            page.create_batch()
            batch = page.batch
            batch.record_page(batch.state['dramas'][0], [{'id': '1', 'name': '二创'}, {'id': '2', 'name': '二创'}], 1)
            with patch('src.recreation_workflow.QMessageBox.question', return_value=QMessageBox.No), \
                    patch.object(page, '_start_browser_task') as start:
                page.request_processing_import('md5', str(batch.folder), ['4100_1'])
                start.assert_not_called()
                self.assertEqual(page.workspace.inputs['md5'], [])
            with patch('src.recreation_workflow.QMessageBox.question', return_value=QMessageBox.Yes), \
                    patch.object(page, '_start_browser_task', side_effect=lambda *a, **k: page._set_collection_busy(True)) as start:
                page.request_processing_import('md5', str(batch.folder), ['4100_1', '4100_2'])
                self.assertEqual(start.call_args.kwargs['identities'], ['4100_1', '4100_2'])
            source = Path(folder) / 'source.mp4'
            source.write_bytes(b'video')
            batch = RecreationBatch.load(batch.folder)
            batch.state['sources'][0].update(path=str(source), download_status='downloaded')
            batch.save()
            page.collection_result({'completed': 1, 'failed': 1, 'skipped': 0, 'stopped': False})
            page.collection_finished()
            self.assertEqual([x['video_id'] for x in page.workspace.inputs['md5']], ['4100_1'])
            self.assertEqual(page.workspace.inputs['micro'], [])
            self.assertEqual(page.md5.table.rowCount(), 1)
            page.close()

    def test_real_md5_processing_persists_to_source_batch_and_appears_in_upload(self):
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            page.drama_input.setPlainText('4100-测试剧')
            page.create_batch()
            source = Path(folder) / 'source.mp4'
            run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x240:rate=15:duration=1', '-c:v', 'libx264', str(source)])
            page.batch.add_local_sources([str(source)], page.batch.state['dramas'][0])
            identity = page.batch.state['sources'][0]['video_id']
            page.complete_processing_import('md5', str(page.batch.folder), [identity])
            page.md5.uploader.setText('TEST')
            page.set_checked(page.md5.table, 'all')
            page.md5.start()
            deadline = time.monotonic() + 15
            while page.md5.busy and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.01)
            self.assertFalse(page.md5.busy)
            self.assertEqual(len(RecreationBatch.load(page.batch.folder).state['outputs']), 1, page.md5.status.text())
            self.assertEqual(len(page.catalog), 1)
            self.assertEqual(page.catalog[0]['mode'], 'md5')
            page.view_products('micro')
            self.assertEqual(page.output_table.rowCount(), 0)
            page.view_products('md5')
            self.assertEqual(page.output_table.rowCount(), 1)
            page.close()

    def test_effect_preview_plays_without_registering_product_or_requiring_uploader(self):
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            page.drama_input.setPlainText('4100-测试剧')
            page.create_batch()
            source = Path(folder)/'source.mp4'
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=30:duration=4',
                 '-c:v','libx264',str(source)])
            page.batch.add_local_sources([str(source)],page.batch.state['dramas'][0])
            identity = page.batch.state['sources'][0]['video_id']
            page.complete_processing_import('micro',str(page.batch.folder),[identity])
            panel = page.micro
            page.set_checked(panel.table,'all')
            panel.preview_length.setValue(2)
            panel.preview_start.setValue(1)
            panel.micro_settings.mirror.setChecked(True)
            panel.micro_settings.randomize.setChecked(True)
            panel.start(preview=True)
            deadline = time.monotonic()+20
            while panel.busy and time.monotonic()<deadline:
                self.app.processEvents()
                time.sleep(.01)
            self.assertFalse(panel.busy)
            self.assertIsNotNone(panel.preview_dialog,panel.status.text())
            self.assertEqual(RecreationBatch.load(page.batch.folder).state['outputs'],[])
            self.assertEqual(page.catalog,[])
            self.assertTrue(panel.micro_settings.mirror.isChecked())
            self.assertTrue(panel.effect_button.isEnabled())
            self.assertTrue(panel.preview_dialog.player.source().isLocalFile())
            cache = Path(panel.preview_cache.name)
            self.assertTrue((cache/'preview.mp4').is_file())
            panel.preview_dialog.accept()
            self.assertIsNone(panel.preview_dialog.player)
            self.assertFalse(cache.exists())
            panel.uploader.setText('TEST');panel.count.setValue(2)
            for change in (False,True):
                if change:panel.micro_settings.fields['brightness'].setValue(.08)
                with patch('src.recreation_processing.generate_variants',return_value={'outputs':[],'failed':[]}) as generate:
                    panel.start()
                    deadline=time.monotonic()+10
                    while panel.busy and time.monotonic()<deadline:
                        self.app.processEvents();time.sleep(.01)
                frozen=generate.call_args.kwargs['resolved_plans']
                self.assertEqual(len(frozen),0 if change else 1)
            panel.preview_start.setValue(100)
            panel.start(preview=True)
            deadline = time.monotonic()+10
            while panel.busy and time.monotonic()<deadline:
                self.app.processEvents()
                time.sleep(.01)
            self.assertIn('预览起点',panel.status.text())
            self.assertEqual(RecreationBatch.load(page.batch.folder).state['outputs'],[])
            panel.preview_cache.cleanup()
            page.close()

    def test_upload_groups_do_not_mix_dramas_or_exceed_fifty(self):
        with tempfile.TemporaryDirectory() as folder:
            page = self.page(folder)
            path = Path(folder) / 'ready.mp4'
            path.write_bytes(b'video')
            page.catalog = [{'path': str(path), 'batch_folder': folder, 'mode': 'md5', 'drama': drama,
                'metadata': {}, 'upload_drama_info': {'drama_platform_id': identity, 'drama_name': drama}}
                for identity, drama, n in [('4100', '第一剧', 51), ('4200', '第二剧', 2)] for _ in range(n)]
            page.output_table.setRowCount(53)
            for i in range(53):
                page.output_table.setItem(i, 0, page._check_item(str(i), {str(i)}))
            page.upload_director.setText('编导')
            page.platform.uploader_initials.setText('TEST')
            with patch.object(page, 'continue_upload'):
                page.begin_upload()
            self.assertEqual([len(x['outputs']) for x in page.upload_groups], [50, 1, 2])
            self.assertEqual([x['drama_id'] for x in page.upload_groups], ['4100', '4100', '4200'])
            self.assertEqual([x['sequence_start'] for x in page.upload_groups], [1, 51, 1])
            page.close()
