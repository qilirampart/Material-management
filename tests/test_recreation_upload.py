import unittest
import json
import subprocess
from unittest.mock import patch
from src.recreation_upload import upload_files, upload_script, record_upload, reconcile_upload
from src.recreation import RecreationBatch
from pathlib import Path
import tempfile


class UploadTests(unittest.TestCase):
    def test_actual_browser_script_guards_identity_unsaved_state_and_clicks_only_upload(self):
        script = json.dumps(upload_script(['case.mp4'], '4100', start=True))
        setup = """
        let clicks=0, saved='', drama='4100', departments=['客户端二组'];
        const manager={uploadVideoFiles:[],isOssUploading:false};
        const input={files:[{name:'case.mp4'}],closest:()=>box};
        const box={querySelectorAll:()=>[],querySelector:()=>({disabled:false,title:'上传选中文件',click:()=>clicks++})};
        const d={querySelector:s=>s==='#isShowOssUpload'?{value:'1'}:s==='#uploadSaveFlag'?{value:saved}:input};
        const w={MaterialInfoDlg:manager,formSelects:{value:n=>n==='bookIdSelect'?[drama]:departments}};
        const nested={src:'https://market.wuread.cn/material_add',contentWindow:w,contentDocument:d};
        const main={src:'https://market.wuread.cn/market-admin/material/material',contentDocument:{querySelectorAll:()=>[nested]}};
        const document={querySelectorAll:()=>[{src:'https://market.wuread.cn/market-admin/home',id:'iframe9'},main]};
        """
        code = setup + f"const script={script};" + """
        const good=eval(script);saved='new';const dirty=eval(script);
        saved='';drama='wrong';const wrong=eval(script);
        drama='4100';departments=['other'];const dept=eval(script);
        console.log(JSON.stringify({good,dirty,wrong,dept,clicks}));
        """
        result = subprocess.run(['node', '-e', code], capture_output=True, text=True, encoding='utf-8', check=True)
        data = json.loads(result.stdout)
        self.assertTrue(data['good']['started'])
        self.assertEqual(data['clicks'], 1)
        self.assertIn('未提交', data['dirty']['error'])
        self.assertIn('剧目', data['wrong']['error'])
        self.assertIn('部门', data['dept']['error'])
    def test_only_upload_control_is_clicked_never_save_or_submit(self):
        script = upload_script(['case.mp4'], '4100', start=True)
        self.assertIn('button.fileinput-upload', script)
        self.assertIn('客户端二组', script)
        self.assertIn('不会覆盖', script)
        self.assertNotIn('.submit(', script)
        self.assertNotIn('saveDraft', script)
        self.assertNotIn('document.cookie', script)

    def test_waits_for_both_server_and_preview_success(self):
        states = [{'started': True}, {'running': False, 'uploaded': 0, 'success': 0, 'failed': 0},
                  {'running': True, 'uploaded': 0, 'success': 0, 'failed': 0},
                  {'running': False, 'uploaded': 2, 'success': 2, 'failed': 0}]
        with patch('src.recreation_upload.evaluate_edge_page', side_effect=states) as evaluate, \
                patch('src.recreation_upload.time.sleep'):
            result = upload_files('ws://test', ['one.mp4', 'two.mp4'], '4100')
            self.assertEqual(result['uploaded'], 2)
            self.assertEqual(evaluate.call_count, 4)

    def test_reconcile_only_resolves_reviewed_files_and_keeps_unselected_uncertain(self):
        with tempfile.TemporaryDirectory() as folder:
            batch = RecreationBatch.create(Path(folder), [{'id': '4100', 'name': '测试剧'}])
            paths = [str(batch.folder / f'{i}.mp4') for i in range(3)]
            record_upload({'folder': batch.folder, 'drama_id': '4100',
                           'outputs': [{'path': p} for p in paths]}, 'abc', 'review')
            self.assertEqual(reconcile_upload(batch.folder, {paths[0]}, True), 1)
            self.assertEqual(reconcile_upload(batch.folder, {paths[1]}, False), 1)
            entries = RecreationBatch.load(batch.folder).state['uploads']
            self.assertEqual({entry['status']: entry['files'] for entry in entries},
                             {'review': [paths[2]], 'uploaded': [paths[0]]})

    def test_existing_unsaved_form_is_not_overwritten_or_retried(self):
        with patch('src.recreation_upload.evaluate_edge_page', return_value={'error': '存在未提交内容'}) as evaluate:
            with self.assertRaisesRegex(RuntimeError, '未提交'):
                upload_files('ws://test', ['case.mp4'], '4100')
            self.assertEqual(evaluate.call_count, 1)

    def test_stop_before_transfer_does_not_click_upload(self):
        with patch('src.recreation_upload.evaluate_edge_page') as evaluate:
            result = upload_files('ws://test', ['case.mp4'], '4100', should_stop=lambda: True)
            self.assertTrue(result['stopped'])
            evaluate.assert_not_called()

    def test_uncertain_partial_transfer_never_clicks_again(self):
        states = [{'started': True}, {'running': True, 'uploaded': 1, 'success': 1, 'failed': 1},
                  {'running': False, 'uploaded': 1, 'success': 1, 'failed': 1}]
        with patch('src.recreation_upload.evaluate_edge_page', side_effect=states) as evaluate, \
                patch('src.recreation_upload.time.sleep'):
            with self.assertRaisesRegex(RuntimeError, '未全部成功'):
                upload_files('ws://test', ['one.mp4', 'two.mp4'], '4100')
        self.assertEqual([('"start": true' in call.args[1]) for call in evaluate.call_args_list],
                         [True, False, False])
