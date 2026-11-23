"""Opt-in submission through the native Zh投 form, with a per-batch receipt."""
import json
import re
import time

from src.edge_cdp import evaluate_edge_page
from src.recreation_platform import RecreationPlatformError


class SubmitNotStarted(RecreationPlatformError):
    """The platform was inspected, but the final confirmation was not clicked."""


def submit_script(step, attempt, names=(), drama_id='', director=''):
    payload = json.dumps({'step':step,'attempt':attempt,'names':list(names),'drama':str(drama_id),
                          'director':director},ensure_ascii=False)
    return r"""(() => {
      const args=__PAYLOAD__, same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
      if(location.origin!=='https://market.wuread.cn')return {error:'当前地址不是已核验的智投站点'};
      const route=(frame,path)=>{try{
        const url=new URL(frame.src,location.href);return url.origin===location.origin&&url.pathname===path;
      }catch{return false;}};
      const main=[...document.querySelectorAll('iframe')].filter(f=>route(f,'/market-admin/material/material'));
      if(main.length!==1||!main[0].contentDocument)return {error:'无法确认智投素材管理页'};
      const parent=main[0].contentDocument;
      const forms=[...parent.querySelectorAll('iframe')].filter(f=>route(f,'/market-admin/material/material/material_add'));
      const jobs=window.__dzSubmitAttempts ||= Object.create(null);
      const job=jobs[args.attempt];
      if(args.step==='status'){
        return job?.receipt?{receipt:job.receipt}:
          (job?.confirmed&&forms.length===1&&forms[0]===job.frame?{pending:true}:{missing:true});
      }
      if(args.step==='clean'){
        if(!job?.receipt||job.receipt.partial)return {closed:false};
        if(!forms.length){delete jobs[args.attempt];return {closed:true};}
        if(forms.length!==1||forms[0]!==job.frame)return {closed:false};
        const doc=job.frame.contentDocument;
        const title=/^上传成功素材清单（共 \d+ 个，\d+ 本书）$/;
        const dialogs=[...doc.querySelectorAll('.layui-layer')].filter(el=>
          title.test(el.querySelector('.layui-layer-title')?.innerText.trim()||''));
        const close=dialogs.length===1&&dialogs[0].querySelector('.layui-layer-btn1');
        if(job.closeClicked)return {waiting:true};
        if(!close||close.innerText.trim()!=='关闭')return {closed:false};
        job.closeClicked=true;close.click();return {waiting:true};
      }
      const frame=forms[0], doc=frame?.contentDocument, win=frame?.contentWindow;
      if(forms.length!==1||!doc||!win)return {error:'未找到唯一的本批上传表单'};
      const manager=win.MaterialInfoDlg, api=win.formSelects||win.layui?.formSelects;
      const input=doc.querySelector('#uploadVideoFileOss');
      const box=input?.closest('.file-input');
      const field=name=>(api?.value(name,'val')||[]).map(String);
      if(!manager||typeof manager.showOssUploadResult!=='function'||!box||
         doc.querySelector('#isShowOssUpload')?.value!=='1'||
         doc.querySelector('#sourceType')?.value!=='video'||
         doc.querySelector('input[name="viewRange"]:checked')?.value!=='1'||
         doc.querySelector('#uploadSaveFlag')?.value!=='new')
        return {error:'平台没有可确认的新增视频表单'};
      if(!same(field('bookIdSelect'),[args.drama])||!same(field('deptSelect'),['客户端二组'])||
         !same(field('directorSelect'),[args.director]))return {error:'剧目、编导或可见范围不匹配'};
      const videos=manager.uploadVideoFiles||[], paths=videos.map(x=>String(x.path||'')).sort();
      const filename=x=>String(x.fileName||x.name||'').replace(/\.mp4$/i,'');
      const filenames=videos.map(filename).sort();
      const expected=args.names.map(x=>x.replace(/\.mp4$/i,'')).sort();
      const errors=box.querySelectorAll('.file-preview-frame.file-preview-error').length;
      const completed=box.querySelectorAll('.file-preview-frame.file-preview-success').length;
      if(manager.isOssUploading||manager.isOssUploadInFlight?.()||manager.selectedOssEntries?.length||
         errors||completed!==args.names.length||videos.length!==args.names.length||
         videos.some(x=>!x.directOss)||!paths.every(Boolean)||new Set(paths).size!==videos.length||
         !same(filenames,expected)||!same([...input.files].map(x=>x.name),args.names))
        return {error:'平台成功文件名单与本批不一致，未提交'};
      const modals=[document,parent,doc].flatMap(d=>[...d.querySelectorAll('.layui-layer-dialog')])
        .filter(node=>node.getClientRects().length);
      if(args.step==='open'){
        if(job||modals.length)return {error:'已有确认窗口或本批已启动，请人工核对'};
        const controls=[...doc.querySelectorAll('button,a')].filter(x=>
          x.innerText.trim()==='提交审核'&&x.getAttribute('onclick')==='MaterialInfoDlg.addSubmit(0)'&&
          x.getClientRects().length&&!x.disabled);
        if(controls.length!==1)return {error:'未找到唯一的智投提交审核按钮'};
        jobs[args.attempt]={frame,paths}; controls[0].click();return {opened:true};
      }
      if(args.step!=='confirm'||!job||job.confirmed||job.frame!==frame||!same(job.paths,paths))
        return {error:'当前表单已改变或本批已确认，请人工核对'};
      if(!modals.length)return {pending:true};
      const modal=modals[0], content=modal.querySelector('.layui-layer-content')?.innerText.trim();
      const button=modal.querySelector('.layui-layer-btn0');
      if(modals.length!==1||content!=='确定提交审核吗？审核中不可修改素材信息'||
         !button||!['确定','确认'].includes(button.innerText.trim()))
        return {error:'平台未出现预期的提交审核确认，请检查页面提示'};
      // Observe the platform's existing success/partial-success callback. The
      // native form still validates and sends the request itself.
      const show=manager.showOssUploadResult;
      manager.showOssUploadResult=function(items, details, onClose){
        manager.showOssUploadResult=show;
        job.receipt={partial:typeof details!=='string'||details!==''||!Array.isArray(items),
          items:Array.isArray(items)?items.map(it=>({id:String(it?.id??''),drama:String(it?.bookId??'')})):[]};
        return show.call(this,items,details,onClose);
      };
      job.confirmed=true;
      button.click();
      return {confirmed:true};
    })()""".replace('__PAYLOAD__',payload)


def submit_uploaded_batch(ws_url, attempt, names, drama_id, director='', *, should_stop=None, timeout=120):
    if should_stop and should_stop():
        return None
    if not names or len(names) != len(set(names)):
        raise SubmitNotStarted('提交名单为空或包含重名文件，未提交')

    def evaluate(step):
        result = evaluate_edge_page(ws_url, submit_script(step,attempt,names,drama_id,director))
        if not isinstance(result,dict):
            raise RecreationPlatformError('无法确认智投提交状态，结果待核对')
        return result

    result = evaluate('open')
    if result.get('error'):
        raise SubmitNotStarted(result['error'])
    if not result.get('opened'):
        raise RecreationPlatformError('无法确认智投提交状态，结果待核对')
    deadline = time.monotonic()+5
    while time.monotonic()<deadline:
        if should_stop and should_stop():
            return None
        result=evaluate('confirm')
        if result.get('confirmed'):
            break
        if result.get('error'):
            raise SubmitNotStarted(result['error'])
        if not result.get('pending'):
            raise RecreationPlatformError('无法确认智投提交状态，结果待核对')
        time.sleep(.2)
    else:
        raise SubmitNotStarted('智投没有显示审核确认，请在平台查看，未代为确认')
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        result=evaluate('status')
        if result.get('receipt'):
            receipt=result['receipt']
            items=receipt.get('items') or []
            if not isinstance(items,list) or not all(isinstance(it,dict) for it in items):
                break
            ids=[it.get('id','') for it in items]
            if (receipt.get('partial') is False and len(ids)==len(names) and len(set(ids))==len(ids)
                and all(isinstance(i,str) and re.fullmatch(r'[1-9]\d*',i) for i in ids)
                and all(it.get('drama')==str(drama_id) for it in items)):
                return ids
            break
        if not result.get('pending'):
            break
        time.sleep(.6)
    raise RecreationPlatformError('智投未返回本批完整审核回执，提交结果待核对；不会再次提交')


def close_submission_receipt(ws_url, attempt):
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        result=evaluate_edge_page(ws_url,submit_script('clean',attempt))
        if result.get('closed'):
            return True
        if not result.get('waiting'):
            return False
        time.sleep(.25)
    return False
