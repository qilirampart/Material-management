import unittest
import json
import subprocess
from unittest.mock import patch

from src.recreation_platform import RecreationPlatformError
from src.recreation_submit import submit_uploaded_batch, submit_script


class SubmitTests(unittest.TestCase):
    def test_browser_clicks_native_control_once_and_only_for_exact_form(self):
        scripts=json.dumps([submit_script(s,'batch-q',['case.mp4'],'4100','编导')
                            for s in ('open','confirm','status','clean')],ensure_ascii=False)
        setup=r"""
        const window={}, location={href:'https://market.wuread.cn/market-admin/', origin:'https://market.wuread.cn'};
        let opened=0,confirmed=0,closed=0,forms=true,prompt=false,receipt=false,nativeCount=0;
        const box={querySelectorAll:s=>s.endsWith('-success')?[{}]:[]};
        const input={files:[{name:'case.mp4'}],closest:()=>box};
        const director='编导';
        let departments=['额外部门'];
        const manager={uploadVideoFiles:[{name:'case',path:'media/case',directOss:true}],
          showOssUploadResult(){nativeCount++;receipt=true;}};
        const accept={innerText:'确定',click:()=>{confirmed++;prompt=false;manager.showOssUploadResult([{id:88,bookId:4100}],'',()=>{});}};
        const modal={getClientRects:()=>[{}],querySelector:s=>s==='.layui-layer-content'
          ?{innerText:'确定提交审核吗？审核中不可修改素材信息'}:accept};
        const close={innerText:'关闭',click:()=>{closed++;forms=false;}};
        const layer={querySelector:s=>s==='.layui-layer-title'?{innerText:'上传成功素材清单（共 1 个，1 本书）'}:close};
        const button={innerText:'提交审核',getAttribute:()=> 'MaterialInfoDlg.addSubmit(0)',
          getClientRects:()=>[{}],click:()=>{opened++;prompt=true;}};
        const doc={querySelector:s=>s==='#isShowOssUpload'||s.includes('viewRange')?{value:'1'}
          :s==='#uploadSaveFlag'?{value:'new'}:s==='#sourceType'?{value:'video'}:input,
          querySelectorAll:s=>s==='button,a'?[button]:s==='.layui-layer'&&receipt?[layer]:[]};
        const frame={src:location.origin+'/market-admin/material/material/material_add',contentDocument:doc,
          contentWindow:{MaterialInfoDlg:manager,formSelects:{value:s=>s==='bookIdSelect'?['4100']:s==='directorSelect'?[director]:departments}}};
        const parent={querySelectorAll:s=>s==='iframe'?(forms?[frame]:[]):[]};
        const main={src:location.origin+'/market-admin/material/material',contentDocument:parent};
        const document={querySelectorAll:s=>s==='iframe'?[main]:(prompt?[modal]:[])};
        """
        result=subprocess.run(['node','-e',setup+'const steps='+scripts+''';
          const wrong=eval(steps[0]);departments=['客户端二组'];
          const first=eval(steps[0]),duplicateOpen=eval(steps[0]);
          manager.uploadVideoFiles[0].path='changed';const changed=eval(steps[1]);
          manager.uploadVideoFiles[0].path='media/case';
          const acceptOnce=eval(steps[1]),duplicateConfirm=eval(steps[1]),ack=eval(steps[2]);
          const cleaning=eval(steps[3]),cleaned=eval(steps[3]);
          console.log(JSON.stringify({wrong,first,duplicateOpen,changed,acceptOnce,duplicateConfirm,ack,cleaning,
            cleaned,opened,confirmed,closed,nativeCount}));
          '''],encoding='utf-8',capture_output=True,check=True)
        data=json.loads(result.stdout)
        for key in ('wrong','duplicateOpen','changed','duplicateConfirm'):
            self.assertIn('error',data[key])
        self.assertTrue(data['cleaned']['closed'])
        self.assertEqual(data['ack']['receipt'],{'partial':False,'items':[{'id':'88','drama':'4100'}]})
        self.assertEqual([data[k] for k in ('opened','confirmed','closed','nativeCount')],[1,1,1,1])

    def test_delayed_receipt_requires_unique_matching_platform_ids(self):
        responses = [{'opened': True}, {'confirmed': True}, {'pending': True},
                     {'receipt': {'partial': False, 'items': [
                        {'id': '101', 'drama': '4100'}, {'id': '102', 'drama': '4100'}]}}]
        with patch('src.recreation_submit.evaluate_edge_page', side_effect=responses) as evaluate, \
             patch('src.recreation_submit.time.sleep'):
            result = submit_uploaded_batch('ws://test', 'abc', ['a.mp4','b.mp4'], '4100')
        self.assertEqual(result, ['101','102'])
        calls = [call.args[1] for call in evaluate.call_args_list]
        self.assertEqual(sum('"step": "open"' in x for x in calls), 1)
        self.assertEqual(sum('"step": "confirm"' in x for x in calls), 1)

    def test_partial_or_wrong_receipt_does_not_retry_confirmation(self):
        for partial, ids, drama in [(True, ['100','101'], '4100'),
            (False, ['100'], '4100'), (False, ['100','100'], '4100'), (False, ['100','101'], '4101')]:
            responses = [{'opened': True}, {'confirmed': True}, {'receipt': {'partial': partial,
                'items': [{'id': i, 'drama': drama} for i in ids]}}]
            with self.subTest(partial=partial, ids=ids, drama=drama), \
                 patch('src.recreation_submit.evaluate_edge_page', side_effect=responses) as evaluate:
                with self.assertRaisesRegex(RecreationPlatformError, '待核对'):
                    submit_uploaded_batch('ws://test','abc',['a.mp4','b.mp4'],'4100')
                self.assertEqual(evaluate.call_count,3)

    def test_no_call_if_paused_before_submit(self):
        with patch('src.recreation_submit.evaluate_edge_page') as evaluate:
            self.assertIsNone(submit_uploaded_batch('ws://test','abc',['a.mp4'],'4100',should_stop=lambda:True))
            evaluate.assert_not_called()

    def test_pause_after_opening_native_prompt_never_confirms(self):
        with patch('src.recreation_submit.evaluate_edge_page', return_value={'opened': True}) as evaluate, \
             patch('src.recreation_submit.time.sleep'):
            choices = iter([False,True])
            result = submit_uploaded_batch('ws://test','abc',['a.mp4'],'4100',
                                           should_stop=lambda:next(choices))
        self.assertIsNone(result)
        evaluate.assert_called_once()
        self.assertIn('"step": "open"',evaluate.call_args.args[1])

    def test_missing_receipt_never_resubmits_even_if_form_closed(self):
        def response(_ws, source):
            if '"step": "open"' in source:
                return {'opened': True}
            if '"step": "confirm"' in source:
                return {'confirmed': True}
            return {'missing': True}
        with patch('src.recreation_submit.evaluate_edge_page',side_effect=response) as evaluate:
            with self.assertRaisesRegex(RecreationPlatformError, '待核对'):
                submit_uploaded_batch('ws://test','abc',['a.mp4'],'4100')
            self.assertEqual(evaluate.call_count,3)
