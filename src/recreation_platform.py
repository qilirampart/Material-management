"""Verified read-only Zh投 endpoints, executed in the user's platform page."""
from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from datetime import date
from pathlib import Path
from src.material_name_filter import normalize_exclude_name,name_is_excluded
from urllib.parse import urlsplit

import requests

from src.edge_cdp import evaluate_edge_page
from src.media import FFmpegCancelled, validate_video
from src.recreation import RecreationStopped, collect_all_pages


class RecreationPlatformError(RuntimeError):
    user_safe = True


class PlatformRateLimited(RecreationPlatformError):
    def __init__(self, seconds):
        super().__init__('平台请求频率受限，请稍后重试')
        self.seconds = max(5, min(120, int(seconds or 5)))


def material_ready_script():
    return """(() => {
      if (location.pathname.includes('/login')) return {status:'login'};
      const frame=[...document.querySelectorAll('iframe')].find(f=>new URL(f.src).pathname==='/market-admin/material/material');
      if(frame?.contentWindow?.Material && frame.contentWindow.$ax) return {status:'ready'};
      const link=[...document.querySelectorAll('a')].find(a=>a.getAttribute('href')?.trim()==='/market-admin/material/material');
      if(link&&!frame){link.click();return {status:'opening'};}
      return {status:'opening'};
    })()"""


def build_platform_job_script(job_id, operation, payload):
    if operation not in {'lookup', 'list', 'source'}:
        raise ValueError('不支持的平台读取操作')
    data = json.dumps({'job': job_id, 'operation': operation, **payload}, ensure_ascii=False)
    return """(() => {
      const args=__PAYLOAD__;
      const frame=[...document.querySelectorAll('iframe')].find(f=>new URL(f.src).pathname==='/market-admin/material/material');
      const w=frame?.contentWindow;
      if(!w?.Material||!w.$ax) return {error:'请先打开素材管理页面并登录'};
      const jobs=window.__dzRecreationJobs ||= {};
      const job=jobs[args.job]={pending:true};
      const done=result=>{if(jobs[args.job]===job){job.pending=false;job.result=result;}};
      let path, params, callback;
      if(args.operation==='lookup'){
        path='/data/1097';
        params={contentType:'video',keyword:args.drama_id};
        callback=data=>{
          if(data.code!==200||!Array.isArray(data.data)){done({error:'剧目查询失败，请确认登录状态'});return;}
          const item=data.data.find(x=>String(x.bookId)===args.drama_id);
          done(item?{id:String(item.bookId),name:String(item.bookName||'')}:{error:'未找到对应的短剧 ID'});
        };
      }else if(args.operation==='list'){
        path='/material/material/cardList';
        params={bookId:args.drama_id,adTargetType:'play',sourceType:'video',
          excludeMaterialName:args.exclude_name||'',
          materialName:args.keyword,uploadTimeBegin:args.start_date,uploadTimeEnd:args.end_date,
          appName:'-1',offset:(args.page-1)*100,limit:100};
        callback=data=>{
          if(!Array.isArray(data.rows)||data.total===undefined){done({error:'素材列表返回异常，请确认登录状态'});return;}
          done({total:data.total,rows:data.rows.map(x=>({id:String(x.id),name:String(x.materialName||''),
            book_id:String(x.bookId||''),size_bytes:Number(x.materialSize)||0}))});
        };
      }else{
        path='/material/material/material_source_url?ids='+encodeURIComponent(args.material_id+',');
        params={};
        callback=data=>{
          const item=Array.isArray(data.data)?data.data.find(x=>String(x.id)===args.material_id):null;
          done(data.code===200&&item?.materialUrl?{url:item.materialUrl}:{error:'无法读取该素材的原始文件地址'});
        };
      }
      const ajax=new w.$ax(w.Feng.ctxPath+path,callback,
        response=>done({error:'平台请求失败（HTTP '+(Number(response?.status)||0)+'），请检查登录或重试',
          status:Number(response?.status)||0,retry_after:Number(response?.getResponseHeader?.('Retry-After'))||5}),true);
      if(args.operation==='lookup'){
        ajax.setContentType('application/json;charset=UTF-8');ajax.setData(JSON.stringify(params));
      }else ajax.set(params);
      ajax.start();
      return {started:true};
    })()""".replace('__PAYLOAD__', data)


def parse_material_page(payload, drama_id, page, size=100):
    rows = payload.get('rows')
    try:
        total = int(payload['total'])
    except (KeyError, ValueError, TypeError):
        raise ValueError('平台未返回有效素材总数') from None
    if not isinstance(rows, list) or total < 0 or len(rows) > size:
        raise ValueError('平台分页数据异常')
    if any(not isinstance(x, dict) or str(x.get('book_id')) != str(drama_id) or not re.fullmatch(r'\d+', str(x.get('id', '')))
           for x in rows):
        raise ValueError('返回素材与目标剧目不一致，已停止采集')
    if total < (page - 1) * size + len(rows):
        raise ValueError('素材数量在采集中发生变化，请重新查询')
    expected = min(size, max(0, total - (page - 1) * size))
    if len(rows) != expected or len({str(x['id']) for x in rows}) != len(rows):
        raise ValueError('平台返回的分页不完整或重复，请重试；已读取内容保留')
    return {'items': rows, 'has_next': page * size < total, 'total': total}


class PlatformMaterialClient:
    def __init__(self, ws_url, *, should_stop=None, on_wait=None):
        self.ws_url = ws_url
        self.should_stop = should_stop or (lambda: False)
        self.last_request_at = 0
        self.on_wait = on_wait

    def _wait(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self._check_stop()
            time.sleep(min(0.2, max(0, deadline - time.monotonic())))

    def _check_stop(self):
        if self.should_stop():
            raise RecreationStopped('已停止，已完成的记录和文件保留')

    def ensure_ready(self):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            self._check_stop()
            result = evaluate_edge_page(self.ws_url, material_ready_script()) or {}
            if result.get('status') == 'ready':
                return
            if result.get('status') == 'login':
                raise RecreationPlatformError('请先在“上传准备”页打开智投并扫码登录')
            time.sleep(0.3)
        raise RecreationPlatformError('素材管理页面未加载完成，请在平台页确认后重试')

    def _request(self, operation, **payload):
        for attempt in range(4):
            self._wait(max(0, 3 - (time.monotonic() - self.last_request_at)))
            self.last_request_at = time.monotonic()
            try:
                return self._request_once(operation, **payload)
            except PlatformRateLimited as exc:
                if attempt == 3:
                    raise
                seconds = exc.seconds * (attempt + 1)
                if self.on_wait:
                    self.on_wait({'phase': 'rate_limited', 'seconds': seconds})
                self._wait(seconds)

    def _request_once(self, operation, **payload):
        self._check_stop()
        job = uuid.uuid4().hex
        result = evaluate_edge_page(self.ws_url, build_platform_job_script(job, operation, payload)) or {}
        if result.get('error'):
            raise RecreationPlatformError(result['error'])
        deadline = time.monotonic() + 90
        try:
            while time.monotonic() < deadline:
                self._check_stop()
                result = evaluate_edge_page(self.ws_url,
                    f'window.__dzRecreationJobs?.[{json.dumps(job)}]') or {}
                if result.get('pending') is False:
                    data = result.get('result', {})
                    if data.get('error'):
                        if data.get('status') == 429:
                            raise PlatformRateLimited(data.get('retry_after'))
                        raise RecreationPlatformError(data['error'])
                    return data
                time.sleep(0.25)
            raise RecreationPlatformError('平台查询超时，请重试；已读取结果保留')
        finally:
            try:
                evaluate_edge_page(self.ws_url, f'delete window.__dzRecreationJobs?.[{json.dumps(job)}]')
            except Exception:
                pass  # Cleanup must not replace the actual query/stop outcome.

    def lookup(self, drama):
        return self._request('lookup', drama_id=drama['id'])

    def fetch_page(self, drama, keyword, page, start_date, end_date, *, exclude_name=''):
        result = self._request('list', drama_id=drama['id'], keyword=keyword, page=page,
                               start_date=start_date, end_date=end_date,exclude_name=normalize_exclude_name(exclude_name))
        return parse_material_page(result, drama['id'], page)

    def source_url(self, material_id):
        if not re.fullmatch(r'\d+', str(material_id)):
            raise ValueError('素材 ID 无效')
        return validate_material_url(self._request('source', material_id=str(material_id))['url'])


def validate_material_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname != 'material.wuread.cn'
            or parsed.username or parsed.password or parsed.port not in {None, 443}):
        raise ValueError('原始文件地址不属于已验证的智投素材服务器')
    return url


def collect_platform_materials(batch, client, start_date, end_date, *, progress=None, should_stop=None,exclude_name=None):
    exclude_name=normalize_exclude_name(batch.state.get('exclude_name','') if exclude_name is None else exclude_name)
    if date.fromisoformat(start_date) > date.fromisoformat(end_date):
        raise ValueError('开始日期不能晚于结束日期')
    dates = {'start': start_date, 'end': end_date}
    if batch.state.get('sources') and batch.state.get('query_dates', dates) != dates:
        raise ValueError('查询日期已改变，请新建批次；原批次素材保留')
    batch.state['query_dates'] = dates
    batch.state['exclude_name']=exclude_name
    batch.state['collection_status'] = 'in_progress'
    batch.save()
    try:
        for index, drama in enumerate(batch.state['dramas'], 1):
            if should_stop and should_stop():
                raise RecreationStopped('已停止查询')
            if progress:
                progress({'phase': 'lookup', 'drama_id': drama['id'], 'index': index,
                          'total': len(batch.state['dramas'])})
            resolved = client.lookup(drama)
            drama['name'] = resolved['name']
            for keyword in ('二创', '精剪原片'):
                expected_total = None
                def fetch(current, page):
                    nonlocal expected_total
                    extra={'exclude_name':exclude_name} if exclude_name else {}
                    payload = client.fetch_page(current, keyword, page, start_date, end_date,**extra)
                    if expected_total is not None and payload['total'] != expected_total:
                        raise ValueError('素材总数在翻页过程中发生变化，请重新查询')
                    expected_total = payload['total']
                    return payload
                def persist_page(current, items, page):
                    batch.record_page(current,[x for x in items if not name_is_excluded(x['name'],exclude_name)],page)
                    if progress:
                        progress({'phase': 'page', 'drama_id': current['id'], 'drama': current['name'],
                                  'keyword': keyword, 'page': page, 'matched': len(batch.state['sources']),
                                  'query_total': expected_total})
                collect_all_pages(drama, fetch, on_page=persist_page, should_stop=should_stop)
        batch.state['collection_status'] = 'complete'
    except RecreationStopped:
        batch.state['collection_status'] = 'paused'
    except Exception:
        batch.state['collection_status'] = 'failed'
        batch.save()
        raise
    batch.save()
    return {'folder': str(batch.folder), 'count': len(batch.state['sources']),
            'excluded':sum(name_is_excluded(x['name'],exclude_name) for x in batch.state['sources'] if x.get('source_material_id')),
            'stopped': batch.state['collection_status'] == 'paused'}


def download_material(url, partial, *, progress=None, should_stop=None):
    validate_material_url(url)
    for attempt in range(3):
        if should_stop and should_stop():
            raise RecreationStopped('下载已停止')
        try:
            return _download_material_once(url, partial, progress=progress, should_stop=should_stop)
        except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError,
                _RetryableDownloadError):
            if attempt == 2:
                raise RecreationPlatformError('视频下载连接中断、超时或文件不完整，尝试 3 次后仍失败；已完成文件保留') from None
            if progress:
                progress({'retry': attempt + 1, 'bytes': 0, 'size': 0, 'speed': 0})
            deadline = time.monotonic() + 2 * (attempt + 1)
            while time.monotonic() < deadline:
                if should_stop and should_stop():
                    raise RecreationStopped('下载已停止')
                time.sleep(min(0.2, max(0, deadline - time.monotonic())))
        except requests.RequestException:
            raise RecreationPlatformError('视频下载请求失败，请重试；已完成文件保留') from None


class _RetryableDownloadError(RuntimeError):
    pass


def _download_material_once(url, partial, *, progress=None, should_stop=None):
    started = time.monotonic()
    last_report = 0
    received = 0
    with requests.get(url, stream=True, allow_redirects=False, timeout=(10, 15)) as response:
        if response.status_code in {408, 429, 500, 502, 503, 504}:
            raise _RetryableDownloadError()
        if response.status_code != 200:
            raise RecreationPlatformError(f'原始视频下载失败（HTTP {response.status_code}），请重试')
        total = int(response.headers.get('content-length') or 0)
        if total and shutil.disk_usage(Path(partial).parent).free < total + 64 * 1024 * 1024:
            raise RecreationPlatformError('磁盘空间不足，请更换保存目录或释放空间')
        with Path(partial).open('wb') as stream:
            for chunk in response.iter_content(256 * 1024):
                if should_stop and should_stop():
                    raise RecreationStopped('下载已停止')
                if not chunk:
                    continue
                stream.write(chunk)
                received += len(chunk)
                now = time.monotonic()
                if progress and now - last_report >= 0.25:
                    progress({'bytes': received, 'size': total,
                              'speed': received / max(0.001, now - started)})
                    last_report = now
        if not received or (total and received != total):
            raise _RetryableDownloadError()


def download_platform_materials(batch, client, identities=None, *, transfer=None, progress=None, should_stop=None):
    transfer = transfer or download_material
    chosen = set(identities) if identities is not None else None
    items = [x for x in batch.state['sources'] if x.get('source_material_id')
             and (chosen is None or x['video_id'] in chosen)]
    exclude_name=normalize_exclude_name(batch.state.get('exclude_name',''))
    counts = {'completed': 0, 'failed': 0, 'skipped': 0, 'excluded':0,'stopped': False, 'folder': str(batch.folder)}
    for index, item in enumerate(items, 1):
        if should_stop and should_stop():
            counts['stopped'] = True
            break
        if name_is_excluded(item['name'],exclude_name):
            counts['excluded']+=1
            if progress:progress({'phase':'excluded','video_id':item['video_id'],'index':index,'total':len(items),'drama':item['drama']})
            continue
        if item.get('path') and Path(item['path']).is_file() and item['download_status'] == 'downloaded':
            counts['skipped'] += 1
            continue
        event = {'video_id': item['video_id'], 'index': index, 'total': len(items), 'drama': item['drama']}
        try:
            if progress:
                progress({**event, 'phase': 'resolving'})
            target = batch.download_target(item)
            if target.exists():
                metadata = validate_video(target, should_stop=should_stop)
                item.update(path=str(target.resolve()), metadata=metadata, download_status='downloaded')
                item.pop('download_error', None)
            else:
                url = client.source_url(item['source_material_id'])
                partial = batch.begin_download(item['video_id'])
                transfer(url, partial, should_stop=should_stop,
                         progress=(lambda info: progress({**event, 'phase': 'downloading', **info})) if progress else None)
                if progress:
                    progress({**event, 'phase': 'validating'})
                batch.complete_download(item['video_id'], should_stop=should_stop)
            counts['completed'] += 1
            batch.save()
            if progress:
                progress({**event, 'phase': 'downloaded'})
        except (RecreationStopped, FFmpegCancelled):
            item.update(download_status='pending', path='')
            batch.save()
            counts['stopped'] = True
            break
        except Exception as exc:
            message = str(exc) if isinstance(exc, (RecreationPlatformError, ValueError)) else type(exc).__name__
            batch.fail_download(item['video_id'], message)
            counts['failed'] += 1
            if progress:
                progress({**event, 'phase': 'failed', 'message': message})
    return counts
