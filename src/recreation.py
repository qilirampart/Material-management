"""Isolated recreation batches and a platform-neutral, fail-closed collection contract."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from src.batch import save_json
from src.task_input import local_files_to_rows
from src.upload import safe_filename_part
from src.media import validate_video
from src.material_name_filter import normalize_exclude_name


class RecreationStopped(RuntimeError):
    pass


def parse_dramas(text):
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.fullmatch(r'(\d{1,25})(?:\s*[-－]\s*(.+))?', line)
        if not match:
            raise ValueError('每行填写剧目 ID 或“ID-剧名”')
        drama_id, name = match.group(1), (match.group(2) or '').strip()
        previous = result.get(drama_id, {}).get('name', '')
        if previous and name and previous != name:
            raise ValueError(f'剧目 {drama_id} 对应了不同剧名，请检查')
        result[drama_id] = {'id': drama_id, 'name': name or previous}
    if not result:
        raise ValueError('请至少填写一个剧目 ID')
    return list(result.values())


def collect_all_pages(drama, fetch_page, *, on_page=None, should_stop=None):
    """Adapter must return items and an explicit boolean has_next for each page.

    fetch_page runs in the platform's own authenticated browser session. No
    cookies or authentication headers are passed through this contract.
    """
    collected = {}
    previous_pages = set()
    for page in range(1, 10001):
        if should_stop and should_stop():
            raise RecreationStopped('采集已停止，已读取的页面可保留')
        payload = fetch_page(drama, page)
        items = payload.get('items')
        if not isinstance(items, list) or not isinstance(payload.get('has_next'), bool):
            raise ValueError('无法确认分页状态，未将本剧标记为采集完成')
        identities = tuple(str(item.get('id') or '') for item in items)
        if any(not identity for identity in identities):
            raise ValueError('页面素材缺少唯一 ID，采集已停止')
        if identities in previous_pages or (not items and payload['has_next']):
            raise ValueError('分页未前进，采集已停止；已读取内容可保留')
        previous_pages.add(identities)
        matching = [item for item in items if any(key in str(item.get('name', ''))
                                                  for key in ('二创', '精剪原片'))]
        for item in matching:
            collected.setdefault(str(item['id']), item)
        if on_page:
            on_page(drama, matching, page)
        if not payload['has_next']:
            return list(collected.values())
    raise ValueError('页数超出安全范围，请缩小查询条件')


class RecreationBatch:
    def __init__(self, folder, state):
        self.folder = Path(folder).resolve()
        self.state = state

    @classmethod
    def create(cls, root, dramas, *, exclude_name=''):
        exclude_name=normalize_exclude_name(exclude_name)
        run_id = datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6]
        folder = Path(root) / '素材再创作' / run_id
        folder.mkdir(parents=True, exist_ok=False)
        batch = cls(folder, {'schema': 1, 'dramas': dramas, 'sources': [], 'outputs': [],
                             'collection_status': 'not_started','exclude_name':exclude_name})
        batch.save()
        return batch

    @classmethod
    def load(cls, folder, *, recover_interrupted=True):
        folder = Path(folder)
        state = json.loads((folder / 'recreation.json').read_text(encoding='utf-8'))
        if not isinstance(state, dict) or state.get('schema') != 1 or not all(isinstance(state.get(k), list)
                                             for k in ('dramas', 'sources', 'outputs')):
            raise ValueError('不是有效的再创作批次')
        if not state['dramas'] or any(not isinstance(x, dict) or not x.get('id')
                                      or not isinstance(x.get('name'), str) for x in state['dramas']):
            raise ValueError('批次剧目信息不完整')
        for item in state['sources']:
            if not isinstance(item, dict) or not all(isinstance(item.get(key), str) for key in
                    ('video_id', 'drama_id', 'drama', 'name', 'path', 'download_status')):
                raise ValueError('批次来源信息不完整')
        for item in state['outputs']:
            if not isinstance(item, dict) or not all(isinstance(item.get(key), str)
                    for key in ('path', 'drama', 'mode')) or not isinstance(item.get('metadata'), dict):
                raise ValueError('批次成品信息不完整')
        uploads = state.get('uploads', [])
        if not isinstance(uploads, list) or any(not isinstance(x, dict) or not isinstance(x.get('files'), list)
                or any(not isinstance(p, str) for p in x['files']) for x in uploads):
            raise ValueError('批次上传记录不完整')
        batch = cls(folder, state)
        normalize_exclude_name(state.get('exclude_name',''))
        interrupted = False
        if recover_interrupted and state.get('collection_status') == 'in_progress':
            state['collection_status'] = 'paused'
            interrupted = True
        for item in batch.state['sources']:
            if recover_interrupted and item.get('download_status') == 'downloading':
                item.update(download_status='pending', path='')
                interrupted = True
        if interrupted:
            batch.save()
        return batch

    def save(self):
        save_json(self.folder / 'recreation.json', self.state)

    def add_local_sources(self, paths, drama):
        existing = {(x['drama_id'], str(Path(x['path']).resolve()).casefold())
                    for x in self.state['sources'] if x.get('path')}
        for row in local_files_to_rows(paths):
            key = (drama['id'], row['local_path'].casefold())
            if key not in existing:
                self.state['sources'].append({
                    'video_id': drama['id'] + '_' + row['video_id'],
                    'drama_id': drama['id'], 'drama': drama['name'] or drama['id'],
                    'path': row['local_path'], 'name': Path(row['local_path']).name,
                    'download_status': 'local',
                    'upload_drama_info': {'drama_platform_id': drama['id'],
                                          'drama_name': drama['name'] or ''},
                })
                existing.add(key)
        self.save()

    def add_outputs(self, outputs):
        existing = {x['path'] for x in self.state['outputs']}
        for item in outputs:
            if item['path'] not in existing:
                self.state['outputs'].append(item)
                existing.add(item['path'])
        self.save()

    def record_page(self, drama, materials, page):
        """Durably retain each collected page before moving to the next one."""
        existing = {x['video_id'] for x in self.state['sources']}
        for item in materials:
            identity = drama['id'] + '_' + str(item['id'])
            if identity in existing:
                continue
            self.state['sources'].append({
                'video_id': identity, 'source_material_id': str(item['id']),
                'drama_id': drama['id'], 'drama': drama['name'] or drama['id'],
                'name': item['name'], 'path': '', 'download_status': 'pending',
                'upload_drama_info': {'drama_platform_id': drama['id'], 'drama_name': drama['name']},
            })
            existing.add(identity)
        self.state['collection_status'] = 'in_progress'
        self.state['last_page'] = {'drama_id': drama['id'], 'page': page}
        self.save()

    def download_target(self, material):
        drama = safe_filename_part(material['drama']) or material['drama_id']
        name = str(material['source_material_id'])
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            raise ValueError('缺少来源素材 ID')
        return self.folder / drama / '原始素材' / (name + '.mp4')

    def source_by_id(self, identity):
        return next(x for x in self.state['sources'] if x['video_id'] == identity)

    def begin_download(self, identity):
        item = self.source_by_id(identity)
        target = self.download_target(item)
        if target.exists():
            raise ValueError('目标视频已存在，未覆盖；请复用已下载结果')
        target.parent.mkdir(parents=True, exist_ok=True)
        item.update(download_status='downloading', path='')
        item.pop('download_error', None)
        self.save()
        return target.with_suffix('.mp4.part')

    def complete_download(self, identity, *, should_stop=None):
        """Run in the download worker after the browser has closed its file."""
        item = self.source_by_id(identity)
        target = self.download_target(item)
        partial = target.with_suffix('.mp4.part')
        metadata = validate_video(partial, should_stop=should_stop)
        partial.replace(target)
        item.update(path=str(target.resolve()), metadata=metadata, download_status='downloaded')
        self.save()

    def fail_download(self, identity, message):
        item = self.source_by_id(identity)
        item.update(download_status='failed', path='', download_error=str(message))
        self.save()
