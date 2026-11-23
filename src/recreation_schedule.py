"""Local daily recreation jobs and download history independent of batch folders."""
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from uuid import uuid4

from src.batch import save_json
from src.material_name_filter import normalize_exclude_name, name_is_excluded
from src.material_variants import VariantOptions, generate_variants
from src.micro_presets import validate_settings
from src.recreation import RecreationBatch
from src.recreation_platform import collect_platform_materials, download_platform_materials


class InvalidSchedule(ValueError):
    def __init__(self):
        super().__init__('定时配置不完整或损坏，请重新设置')


def validate_schedule(task):
    try:
        if (not isinstance(task, dict) or task.get('schema') != 1 or
                not isinstance(task['enabled'], bool) or not re.fullmatch(r'[0-9]+',task['drama'])):
            raise InvalidSchedule()
        if not re.fullmatch(r'[0-9]{2}:[0-9]{2}', task['at']):
            raise InvalidSchedule()
        time.fromisoformat(task['at'])
        start = date.fromisoformat(task['start'])
        if task['last_day'] != '' and date.fromisoformat(task['last_day']) < start:
            raise InvalidSchedule()
        if not isinstance(task['exclude'],str) or not isinstance(task['status'],str):
            raise InvalidSchedule()
        if not isinstance(task.get('attention',False),bool) or not isinstance(task.get('template',''),str):
            raise InvalidSchedule()
        pending, mode, options = task['pending'], task['mode'], task['options']
        if pending is not None:
            window = pending['window']
            if (not isinstance(pending['folder'],str) or not pending['folder'].strip() or
                    not isinstance(window,list) or len(window)!=2 or
                    date.fromisoformat(window[0])>date.fromisoformat(window[1])):
                raise InvalidSchedule()
        if mode == 'download':
            if options is not None:
                raise InvalidSchedule()
        elif mode in ('md5','micro'):
            if (options['mode']!=mode or not options['uploader'].strip() or
                    type(options['variants']) is not int or not 1<=options['variants']<=10):
                raise InvalidSchedule()
            if mode=='micro':
                validate_settings({k:v for k,v in options.items() if k not in ('mode','uploader','variants')})
            else:
                VariantOptions(**options).validate()
        else:
            raise InvalidSchedule()
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise InvalidSchedule() from exc
    return task


class ScheduleStore:
    def __init__(self, directory):
        self.path = Path(directory) / 'recreation-schedule.json'

    def load(self):
        try:
            task = json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise InvalidSchedule() from exc
        return validate_schedule(task)

    def save(self, task):
        validate_schedule(task)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        save_json(self.path, task)

    def rebuild(self, task):
        validate_schedule(task)
        backup = self.path.with_name(f'{self.path.name}.invalid-{uuid4().hex[:8]}')
        with backup.open('xb') as handle:
            handle.write(self.path.read_bytes())
        self.save(task)
        return backup


class DownloadHistory:
    def __init__(self, directory):
        self.path = Path(directory) / 'recreation-download-history.sqlite3'

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        db.execute('CREATE TABLE IF NOT EXISTS downloaded (drama TEXT, material TEXT, PRIMARY KEY (drama, material))')
        return db

    def note(self, drama, material):
        with closing(self._connect()) as db, db:
            db.execute('INSERT OR IGNORE INTO downloaded VALUES (?, ?)', (drama, material))

    def note_batch(self, batch):
        downloaded = [(x['drama_id'], x['source_material_id']) for x in batch.state['sources']
                      if x.get('source_material_id') and x.get('download_status') == 'downloaded']
        if downloaded:
            with closing(self._connect()) as db, db:
                db.executemany('INSERT OR IGNORE INTO downloaded VALUES (?, ?)', downloaded)

    def sync_batches(self, folders):
        for folder in folders:
            try:
                batch = RecreationBatch.load(folder, recover_interrupted=False)
            except (FileNotFoundError, ValueError):
                continue
            self.note_batch(batch)

    def ids(self, drama):
        with closing(self._connect()) as db:
            return {row[0] for row in db.execute('SELECT material FROM downloaded WHERE drama=?', (drama,))}


def make_schedule(drama, at, exclude, mode, uploader, variants, settings, now):
    if not re.fullmatch(r'[0-9]+', drama.strip()):
        raise ValueError('请输入纯数字剧目 ID')
    if not re.fullmatch(r'\d\d:\d\d', at):
        raise ValueError('请输入每天的扫描时间')
    time.fromisoformat(at)
    if mode not in ('download', 'md5', 'micro'):
        raise ValueError('请选择定时处理方式')
    options = None
    if mode != 'download':
        if not uploader.strip():
            raise ValueError('请填写上传人缩写，用于成品命名')
        extra = validate_settings(settings) if mode == 'micro' else {}
        options = asdict(VariantOptions(mode=mode, variants=variants, uploader=uploader.strip(), **extra).validate())
    return {'schema': 1, 'enabled': True, 'drama': drama.strip(), 'at': at,
            'exclude': normalize_exclude_name(exclude), 'mode': mode, 'options': options,
            'start': now.date().isoformat(), 'last_day': '', 'pending': None, 'status': ''}


def due_window(task, now: datetime):
    if not task or not task['enabled']:
        return None
    if task['pending']:
        return tuple(task['pending']['window'])
    today = now.date()
    day = today if now.time() >= time.fromisoformat(task['at']) else today - timedelta(days=1)
    start = max(task['start'], task['last_day'])
    if day.isoformat() <= task['last_day'] or day.isoformat() < start:
        return None
    # On-time runs include today. Catch-up likewise scans through today so a
    # pending run never expires when the laptop wakes the following morning.
    return start, day.isoformat()


def run_schedule(task, batch, client, history, window, should_stop, *, progress=None, queued_ids=()):
    if 'scheduled_sources' not in batch.state:
        if batch.state['collection_status'] != 'complete':
            result = collect_platform_materials(batch, client, *window, progress=progress,
                                               should_stop=should_stop, exclude_name=task['exclude'])
            if result.get('stopped'):
                return {'done': False, 'message': '查询已暂停'}
        seen = history.ids(task['drama'])
        queued_ids = set(queued_ids)
        batch.state['scheduled_sources'] = [s['video_id'] for s in batch.state['sources']
            if s.get('source_material_id') and s['source_material_id'] not in seen
            and s['video_id'] not in queued_ids
            and not name_is_excluded(s['name'], task['exclude'])]
        batch.save()
    selected = batch.state['scheduled_sources']
    if not selected:
        return {'done': True, 'selected': 0, 'message': '本轮没有新素材'}
    history.note_batch(batch)
    counts = download_platform_materials(batch, client, selected, progress=progress, should_stop=should_stop,
        on_saved=lambda item: history.note(item['drama_id'], item['source_material_id']))
    if counts.get('stopped') or counts.get('pause_reason'):
        return {'done': False, 'selected': len(selected),
                'message': counts.get('pause_reason') or '下载未完成，保留本批，继续时只补齐剩余素材'}
    retry_ids = counts['remaining_ids']
    remaining = set(retry_ids)
    ready = [identity for identity in selected if identity not in remaining]
    count = len(ready)
    retry_note = f'；{len(retry_ids)} 条下载失败，已转入待重试下载队列' if retry_ids else ''
    outcome = {'done': True, 'selected': count, 'retry_ids':retry_ids}
    if task['mode'] == 'download' or not ready:
        return {**outcome, 'message': f'已下载 {count} 条新素材'+retry_note}

    # An interrupted worker can leave a completed manifest before the batch
    # save. Import those outputs before scheduling any remaining versions.
    root = batch.folder / '加工成品'
    try:
        options = VariantOptions(**task['options']).validate()
    except ValueError as exc:
        return {'done': False, 'selected': count, 'attention': True, 'message': str(exc)}
    eligible = set(ready)
    for manifest in root.glob('*/manifest.json'):
        data = json.loads(manifest.read_text(encoding='utf-8'))
        if data.get('options') != task['options']:
            continue
        batch.add_outputs([item for item in data['outputs'] if item['source_video_id'] in eligible
                           and Path(item['path']).resolve().is_relative_to(manifest.parent.resolve())
                           and Path(item['path']).is_file()])
    done = {(x.get('source_video_id'), x.get('version')) for x in batch.state['outputs']
            if x.get('requested_options') == task['options'] and Path(x['path']).is_file()}
    versions = {s: [v for v in range(1, options.variants + 1) if (s, v) not in done] for s in ready}
    if any(versions.values()):
        inputs = [s for s in batch.state['sources'] if versions.get(s['video_id'])]
        result = generate_variants(inputs, root, options, should_stop=should_stop,
                                   progress=progress, versions_by_id=versions)
        batch.add_outputs(result['outputs'])
        if result['stopped'] or result['failed']:
            return {'done': False, 'selected': count, 'attention': True,
                    'message': result.get('stop_reason') or f"加工未完成：{len(result['failed'])} 版失败；已完成的成品保留"}
    return {**outcome, 'message': f'完成 {count} 条新素材的加工，成品可在自动上传页核对'+retry_note}
