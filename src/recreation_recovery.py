"""Recover validated orphan products into their original batch, without encoding."""
import json
import re
import subprocess
from copy import deepcopy
from pathlib import Path
from src.recreation import RecreationBatch
from src.material_variants import file_md5
from src.media import (FFmpegCancelled,FFmpegError,validate_video,effective_video_bitrate_bps,
    MAXIMUM_UPLOAD_FILE_SIZE_BYTES,MINIMUM_VIDEO_BITRATE_KBPS,MAXIMUM_UPLOAD_BITRATE_KBPS)
from src.upload import safe_filename_part


def _identity(path):return str(Path(path).resolve()).casefold()


def _source_for(item,batch):
    source=next((x for x in batch.state['sources'] if x['video_id']==item.get('source_video_id')),None)
    if source is None:raise ValueError('来源不在此批次，未恢复')
    if item.get('drama')!=(safe_filename_part(source['drama']) or '未命名剧集'):
        raise ValueError('剧目与来源不一致，未恢复')
    if (not isinstance(item.get('source_path'),str) or
            item['source_path'].replace('\\','/').casefold()!=source['path'].replace('\\','/').casefold()):
        raise ValueError('原片路径与批次来源不一致，未恢复')
    if source['drama_id'] not in {str(x['id']) for x in batch.state['dramas']}:
        raise ValueError('来源剧目不在此批次，未恢复')
    return source


def _batch_for(manifest):
    for folder in manifest.parents:
        if (folder/'recreation.json').is_file():
            if not manifest.parent.is_relative_to((folder/'加工成品').resolve()):
                raise ValueError('请选择来源批次“加工成品”目录中的 manifest.json')
            return RecreationBatch.load(folder,recover_interrupted=False)
    raise ValueError('未找到来源批次 recreation.json；请保留批次与加工目录结构')


def inspect_manifest_recovery(path,*,should_stop=None,progress=None):
    manifest=Path(path).resolve()
    if manifest.name!='manifest.json':raise ValueError('请选择加工记录 manifest.json')
    batch=_batch_for(manifest)
    with manifest.open('rb') as stream:payload=stream.read(64*1024*1024+1)
    if len(payload)>64*1024*1024:raise ValueError('加工记录超过 64 MB，无法打开')
    data=json.loads(payload.decode('utf-8-sig'))
    if (not isinstance(data,dict) or not isinstance(data.get('options'),dict)
            or not isinstance(data.get('outputs'),list) or len(data['outputs'])>10000):
        raise ValueError('不是有效的加工记录')
    seen={_identity(x['path']) for x in batch.state['outputs']};entries=[]
    for index,item in enumerate(data['outputs']):
        if should_stop and should_stop():raise FFmpegCancelled('已停止成品检查')
        entry={'status':'failed','reason':'记录不完整','path':'','drama':'','mode':''}
        if progress:progress({'index':index+1,'total':len(data['outputs'])})
        try:
            if not isinstance(item,dict):raise ValueError('成品记录无效')
            mode=item.get('mode');entry.update(drama=str(item.get('drama','')),mode=str(mode or ''))
            if mode not in {'micro','md5'} or mode!=data['options'].get('mode'):raise ValueError('处理类型不一致')
            source=_source_for(item,batch)
            if not isinstance(item.get('path'),str) or not item['path']:raise ValueError('成品路径缺失')
            # Resolve only the standard file inside THIS run, never an arbitrary
            # external path from JSON. This also handles a moved whole batch.
            target=(manifest.parent/(safe_filename_part(item['drama']) or '未命名剧集')/
                ('微创新' if mode=='micro' else '改md5')/Path(item['path']).name).resolve()
            entry['path']=str(target)
            if not target.is_relative_to(manifest.parent):raise ValueError('成品指向加工目录以外，未恢复')
            if _identity(target) in seen:
                entry.update(status='duplicate',reason='已在成品列表或本次记录中');entries.append(entry);continue
            if not target.is_file():raise ValueError('视频文件缺失')
            for key in ('source_md5','output_md5'):
                if not isinstance(item.get(key),str) or not re.fullmatch(r'[0-9a-fA-F]{32}',item[key]):
                    raise ValueError('成品缺少有效 MD5 处理记录')
            stat=target.stat();signature=(stat.st_size,stat.st_mtime_ns)
            if stat.st_size>MAXIMUM_UPLOAD_FILE_SIZE_BYTES:raise ValueError('视频超过平台 510 MB 上限')
            # Product MD5 is part of this application's processing contract.
            if file_md5(target,should_stop).lower()!=item['output_md5'].lower():raise ValueError('视频与加工记录 MD5 不一致')
            if item['output_md5'].lower()==item['source_md5'].lower():raise ValueError('成品与原片 MD5 相同')
            metadata=validate_video(target,should_stop=should_stop)
            bitrate=effective_video_bitrate_bps(metadata)
            if mode=='micro' and not MINIMUM_VIDEO_BITRATE_KBPS*1000<bitrate<=MAXIMUM_UPLOAD_BITRATE_KBPS*1000:
                raise ValueError('微创新视频码率不在平台范围内')
            if (target.stat().st_size,target.stat().st_mtime_ns)!=signature:raise ValueError('检查期间文件已更改，请重试')
            old_metadata=item.get('metadata') if isinstance(item.get('metadata'),dict) else {}
            combined={**deepcopy(old_metadata),**metadata};combined.pop('cover',None)
            cover=target.with_suffix('.cover.png')
            if cover.is_file() and cover.resolve().is_relative_to(manifest.parent):
                cover_info=old_metadata.get('cover') if isinstance(old_metadata.get('cover'),dict) else {}
                combined['cover']={**deepcopy(cover_info),'path':str(cover.resolve())}
            output=deepcopy(item)
            output.update(path=str(target),metadata=combined,upload_drama_info=deepcopy(source.get('upload_drama_info',{})))
            entry.update(status='ready',reason='可恢复',output=output,signature=signature)
            seen.add(_identity(target))
        except FFmpegCancelled:raise
        except (OSError,ValueError,FFmpegError,TypeError,subprocess.SubprocessError) as exc:entry['reason']=str(exc)[-250:]
        entries.append(entry)
    return {'manifest':str(manifest),'batch_folder':str(batch.folder),
        'batch_name':' / '.join(x['name'] or str(x['id']) for x in batch.state['dramas']),'entries':entries}


def commit_manifest_recovery(plan,indexes):
    batch=RecreationBatch.load(plan['batch_folder'],recover_interrupted=False)
    seen={_identity(x['path']) for x in batch.state['outputs']};outputs=[]
    for index in dict.fromkeys(indexes):
        if not isinstance(index,int) or not 0<=index<len(plan['entries']):raise ValueError('恢复选择无效')
        entry=plan['entries'][index]
        if entry['status']!='ready':raise ValueError('仅能恢复检查通过的成品')
        item=deepcopy(entry['output']);source=_source_for(item,batch);target=Path(item['path'])
        try:stat=target.stat()
        except OSError as exc:raise ValueError('视频已更改或移走，请重新检查') from exc
        if (stat.st_size,stat.st_mtime_ns)!=tuple(entry['signature']):raise ValueError('视频已更改，请重新检查')
        if _identity(target) in seen:continue
        item['upload_drama_info']=deepcopy(source.get('upload_drama_info',{}))
        outputs.append(item);seen.add(_identity(target))
    if outputs:
        batch.state['outputs'].extend(outputs)
        batch.save()
    return batch,len(outputs)
