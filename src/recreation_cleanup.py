"""Explicit, bounded cleanup of registered recreation media, never directories."""
from copy import deepcopy
from pathlib import Path
from src.recreation import RecreationBatch


def signature(path):
    try:
        stat = path.stat()
        return (stat.st_size, stat.st_mtime_ns)
    except FileNotFoundError:
        return None


def _owned(batch, item, kind):
    if not item.get('path'):
        return None
    path = Path(item['path']).resolve()
    if not path.is_relative_to(batch.folder) or path.suffix.lower() != '.mp4':
        return None
    if kind == 'originals':
        if not item.get('source_material_id') or path != batch.download_target(item).resolve():
            return None
    elif not path.is_relative_to(batch.folder/'加工成品'):
        return None
    if path.exists() and not path.is_file():
        return None
    return path


def _entries(batch, scope):
    result, protected = [], 0
    for kind, key in (('originals', 'sources'), ('products', 'outputs')):
        if scope not in {kind, 'all'}:
            continue
        for item in batch.state[key]:
            path = _owned(batch, item, kind)
            if path is None:
                protected += bool(item.get('path'))
                continue
            entry = {'kind': kind, 'path': str(path), 'signature': signature(path),
                     'identity': item['video_id'] if kind == 'originals' else item['path']}
            if kind == 'products':
                cover = path.with_suffix('.cover.png')
                # Never follow a sidecar link outside the batch.
                if cover.resolve().is_relative_to(batch.folder) and (not cover.exists() or cover.is_file()):
                    entry['cover'] = {'path': str(cover.resolve()), 'signature': signature(cover)}
            result.append(entry)
    return result, protected


def plan_cleanup(folders, scope):
    if scope not in {'originals', 'products', 'all'}:
        raise ValueError('清理范围无效')
    plan = {'scope': scope, 'batches': [], 'protected': 0, 'errors': [], 'files': 0, 'bytes': 0}
    seen = set()
    for folder in dict.fromkeys(str(Path(x).resolve()) for x in folders):
        try:
            batch = RecreationBatch.load(folder, recover_interrupted=False)
            entries, protected = _entries(batch, scope)
            plan['protected'] += protected
            plan['batches'].append({'folder': str(batch.folder), 'entries': entries,
                                    'record_signature': signature(batch.folder/'recreation.json')})
            for entry in entries:
                for file in (entry, entry.get('cover', {})):
                    if file.get('signature') and file['path'] not in seen:
                        seen.add(file['path']); plan['files'] += 1; plan['bytes'] += file['signature'][0]
        except (OSError, ValueError):
            plan['errors'].append(folder + '：批次记录不可用，可选择仅移出列表')
    return plan


def execute_cleanup(plan, workspace):
    """Use only after confirmation and while all desktop heavy tasks are idle."""
    result = {'deleted': 0, 'missing': 0, 'errors': list(plan['errors']),
              'protected': plan['protected'], 'sources': {}, 'changed': []}
    for planned in plan['batches']:
        folder = planned['folder']
        try:
            batch = RecreationBatch.load(folder, recover_interrupted=False)
            if signature(batch.folder/'recreation.json') != planned['record_signature']:
                raise ValueError('批次记录已变化，请重新预览清理范围')
            allowed, _ = _entries(batch, plan['scope'])
            # Recompute ownership instead of trusting caller-provided paths.
            if allowed != planned['entries']:
                raise ValueError('文件已变化，请重新预览清理范围')
            removed_sources, removed_outputs = set(), set()
            for entry in allowed:
                path = Path(entry['path'])
                try:
                    if signature(path) != entry['signature']:
                        raise ValueError('文件已变化，未删除')
                    if entry['signature'] is None:
                        result['missing'] += 1
                    else:
                        path.unlink(); result['deleted'] += 1
                except (OSError, ValueError):
                    result['errors'].append(str(path) + '：未能删除，记录保留')
                    continue
                if entry['kind'] == 'originals':
                    removed_sources.add(entry['identity'])
                else:
                    removed_outputs.add(entry['identity'])
                    cover = entry.get('cover')
                    if cover and cover['signature']:
                        try:
                            sidecar = Path(cover['path'])
                            if signature(sidecar) != cover['signature']:
                                raise ValueError('封面已变化')
                            sidecar.unlink(); result['deleted'] += 1
                        except (OSError, ValueError):
                            result['errors'].append(cover['path'] + '：封面未删除')
            for source in batch.state['sources']:
                if source['video_id'] in removed_sources:
                    source.update(path='', download_status='pending')
                    source.pop('metadata', None); source.pop('download_error', None)
            batch.state['outputs'] = [x for x in batch.state['outputs'] if x['path'] not in removed_outputs]
            batch.save()
            result['sources'][folder] = removed_sources
            result['changed'].append(folder)
        except (OSError, ValueError) as exc:
            result['errors'].append(folder + '：' + str(exc) + '；若文件已删除，刷新后会显示缺失')
    # Sync references for successfully saved batches only. Failed saves remain
    # recoverable as missing-file rows instead of pretending the cleanup saved.
    previous = deepcopy((workspace.queue, workspace.inputs))
    for folder, identities in result['sources'].items():
        workspace.inputs = {mode: [x for x in refs if not
            (x['folder'] == folder and x['video_id'] in identities)] for mode, refs in workspace.inputs.items()}
        if identities:
            workspace.queue = [x for x in workspace.queue if x['folder'] != folder]
    try:
        workspace.save()
    except OSError:
        workspace.queue, workspace.inputs = previous
        result['errors'].append('视频清理已执行，但工作区索引未保存；请检查磁盘与目录权限后刷新')
    return result
