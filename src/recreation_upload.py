"""Upload the selected file widget only; never save or submit a platform form."""
import json
import time
from src.edge_cdp import evaluate_edge_page
from src.recreation_platform import RecreationPlatformError


def upload_script(names=None, drama_id=None, *, start=False):
    payload = json.dumps({'names': names or [], 'drama': str(drama_id or ''), 'start': start}, ensure_ascii=False)
    return """(() => {
      const args=__PAYLOAD__;
      const main=[...document.querySelectorAll('iframe')].find(f=>new URL(f.src).pathname==='/market-admin/material/material');
      const frame=[...(main?.contentDocument?.querySelectorAll('iframe')||[])].filter(f=>f.src.includes('material_add')).at(-1);
      if(!frame?.contentDocument)return {error:'请先打开素材上传表单'};
      const w=frame.contentWindow,d=frame.contentDocument,api=w.formSelects||w.layui?.formSelects;
      const input=d.querySelector(d.querySelector('#isShowOssUpload')?.value==='1'?'#uploadVideoFileOss':'#uploadVideoFile');
      const box=input?.closest('.file-input'), manager=w.MaterialInfoDlg;
      if(!input||!box||!manager)return {error:'视频上传控件尚未加载'};
      const previews=[...box.querySelectorAll('.file-preview-frame')];
      const state={uploaded:manager.uploadVideoFiles?.length||0,running:!!manager.isOssUploading,
        success:previews.filter(p=>p.classList.contains('file-preview-success')).length,
        failed:previews.filter(p=>p.classList.contains('file-preview-error')).length,
        progress:box.querySelector('.file-total-progress')?.innerText||'',
        unsaved:!!d.querySelector('#uploadSaveFlag')?.value};
      if(!args.start)return state;
      const names=[...input.files].map(f=>f.name);
      if(JSON.stringify(names)!==JSON.stringify(args.names))return {error:'文件选择与本批次不一致，未启动上传'};
      if(!api?.value('bookIdSelect','val')?.map(String).includes(args.drama))return {error:'平台剧目与当前上传批次不一致'};
      if(JSON.stringify(api?.value('deptSelect','val'))!==JSON.stringify(['客户端二组']))return {error:'可见部门不正确，未上传'};
      if(state.running||state.uploaded||state.unsaved)return {error:'当前表单已有上传或未提交内容，请先手动处理，不会覆盖'};
      const b=box.querySelector('button.fileinput-upload');
      if(!b||b.disabled||b.title!=='上传选中文件')return {error:'未找到可用的上传选中文件按钮'};
      b.click();return {started:true};
    })()""".replace('__PAYLOAD__', payload)


def upload_files(ws_url, names, drama_id, *, progress=None, should_stop=None, timeout=1800):
    if should_stop and should_stop():
        return {'stopped': True, 'message': '已停止自动上传，未启动文件传输'}
    result = evaluate_edge_page(ws_url, upload_script(names, drama_id, start=True))
    if result.get('error') or not result.get('started'):
        raise RecreationPlatformError(result.get('error', '上传未启动'))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # Do not close the browser while its website upload is in flight. A stop
        # request prevents subsequent work and waits for this transfer to finish.
        state = evaluate_edge_page(ws_url, upload_script())
        if state.get('error'):
            raise RecreationPlatformError(state['error'])
        if progress:
            progress(state)
        if not state['running'] and state['uploaded'] == len(names) and state['success'] == len(names):
            return {**state, 'stopped': False}
        if state['failed'] or (not state['running'] and state['uploaded'] < len(names)):
            raise RecreationPlatformError('平台上传未全部成功，请在登录页检查；未自动重复上传或提交')
        time.sleep(1)
    raise RecreationPlatformError('平台上传等待超时，请先查看当前表单；不会自动重复上传')
