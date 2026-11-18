"""Explicit, bounded cleanup of registered recreation media, never directories."""
from copy import deepcopy
from pathlib import Path
import os
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
        if scope not in {kind, 'all', 'managed'}:
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
    if scope == 'managed':
        staging = batch.folder/'upload-staging'
        # Do not traverse symlink/junction directories or accept escaped targets.
        if staging.resolve().is_relative_to(batch.folder):
            for directory, dirs, files in os.walk(staging, followlinks=False):
                dirs[:] = [name for name in dirs if not (Path(directory)/name).is_symlink()
                           and (Path(directory)/name).resolve().is_relative_to(staging)]
                for name in files:
                    path = Path(directory)/name
                    resolved = path.resolve()
                    if path.suffix.lower() == '.mp4' and resolved.is_relative_to(staging) and path.is_file():
                        result.append({'kind': 'staging', 'path': str(resolved),
                                       'signature': signature(path), 'identity': str(resolved)})
    return result, protected


def _selected_entries(entries, selections):
    def selected(path):
        path = Path(path)
        return any(path == item or path.is_relative_to(item) for item in selections)
    return [entry for entry in entries if selected(entry['path']) or
            (entry.get('cover') and selected(entry['cover']['path']))]


def _discover_selected_batches(root, selections, errors):
    """Find records from the selected filesystem scope, not just the recent index."""
    found = set()
    for selected in selections:
        directory = selected if selected.is_dir() else selected.parent
        ancestor = directory
        owner_found = False
        while ancestor.is_relative_to(root):
            if (ancestor/'recreation.json').is_file():
                found.add(str(ancestor))
                owner_found = True
                break
            if ancestor == root:
                break
            ancestor = ancestor.parent
        if owner_found or not selected.is_dir():
            continue
        def unreadable(exc):
            errors.append(str(exc.filename) + '：目录无法读取，未纳入清理')
        for current, dirs, files in os.walk(selected, followlinks=False, onerror=unreadable):
            path = Path(current)
            dirs[:] = [name for name in dirs if (path/name).resolve() == path/name
                       and not (path/name).is_symlink()]
            if 'recreation.json' in files:
                found.add(str(path))
                dirs[:] = []
    return found


def plan_selection(root, folders, paths):
    """Plan only owned media under selected files/directories, never arbitrary files.

    A selected cover includes its product, which is displayed in the confirmation.
    Folder selection is a filter over registered media, not recursive removal.
    """
    root = Path(root).resolve()
    selections = list(dict.fromkeys(Path(path).resolve() for path in paths))
    if not selections or any(not path.is_relative_to(root) for path in selections):
        raise ValueError('请选择素材保存目录内的文件或文件夹')
    plan = {'scope': 'managed', 'root': str(root), 'selections': [str(x) for x in selections],
            'batches': [], 'protected': 0, 'errors': [], 'files': 0, 'bytes': 0}
    seen = set()
    candidates = dict.fromkeys(str(Path(x).resolve()) for x in folders)
    candidates.update(dict.fromkeys(sorted(_discover_selected_batches(root, selections, plan['errors']))))
    for folder in candidates:
        batch_path = Path(folder)
        if not batch_path.is_relative_to(root) or not any(
                batch_path.is_relative_to(x) or x.is_relative_to(batch_path) for x in selections):
            continue
        try:
            batch = RecreationBatch.load(folder, recover_interrupted=False)
            entries, protected = _entries(batch, 'managed')
            entries = _selected_entries(entries, selections)
            plan['protected'] += protected
            if entries:
                plan['batches'].append({'folder': folder, 'entries': entries,
                    'record_signature': signature(batch.folder/'recreation.json')})
            for entry in entries:
                for file in (entry, entry.get('cover', {})):
                    if file.get('signature') and file['path'] not in seen:
                        seen.add(file['path']); plan['files'] += 1; plan['bytes'] += file['signature'][0]
        except (OSError, ValueError) as exc:
            plan['errors'].append(folder + '：批次记录不可用，未纳入清理；' + str(exc))
    return plan


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
            if plan['scope'] == 'managed':
                root = Path(plan['root']).resolve()
                selections = [Path(x).resolve() for x in plan['selections']]
                if not batch.folder.is_relative_to(root) or any(not x.is_relative_to(root) for x in selections):
                    raise ValueError('清理目录越界')
                allowed = _selected_entries(allowed, selections)
            # Recompute ownership instead of trusting caller-provided paths.
            if allowed != planned['entries']:
                raise ValueError('文件已变化，请重新预览清理范围')
            removed_sources, removed_outputs = set(), set()
            for entry in allowed:
                path = Path(entry['path'])
                try:
                    if path.resolve() != path:
                        raise ValueError('文件位置已变化，未删除')
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
                elif entry['kind'] == 'products':
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
            remaining = []
            for job in workspace.queue:
                if job['folder'] == folder:
                    job = {**job, 'identities': [x for x in job['identities'] if x not in identities]}
                if job['identities']:
                    remaining.append(job)
            workspace.queue = remaining
    try:
        workspace.save()
    except OSError:
        workspace.queue, workspace.inputs = previous
        result['errors'].append('视频清理已执行，但工作区索引未保存；请检查磁盘与目录权限后刷新')
    return result
