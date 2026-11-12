"""Durable index and queue for independent recreation batches; never auto-runs."""
import csv
import json
from zipfile import BadZipFile
from pathlib import Path
from src.batch import save_json
from src.recreation import RecreationBatch, parse_dramas
from src.task_input import parse_upload_drama_filename


class RecreationWorkspace:
    def __init__(self, path, root):
        self.path, self.root = Path(path), Path(root)
        self.folders, self.queue = [], []
        self.inputs = {'md5': [], 'micro': []}
        self.last_batch = ''
        self.queue_running = False
        self.load_error = ''
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                raise ValueError('工作区配置无效')
            self.last_batch = data.get('last_batch', '')
            if not isinstance(self.last_batch, str):
                self.last_batch = ''
                raise ValueError('最近批次目录无效')
            candidates = data.get('batches', [])
            if not isinstance(candidates, list):
                raise ValueError('批次索引无效')
            for folder in [*candidates, self.last_batch]:
                if isinstance(folder, str) and folder and folder not in self.folders:
                    self.folders.append(folder)
            self.queue = data.get('download_queue', [])
            self.inputs = data.get('processing_inputs', self.inputs)
            if not isinstance(self.queue, list) or not isinstance(self.inputs, dict):
                raise ValueError('工作区任务索引无效')
            for mode in ('md5', 'micro'):
                entries = self.inputs.setdefault(mode, [])
                if not isinstance(entries, list) or any(not isinstance(x, dict) or
                        not all(isinstance(x.get(k), str) for k in ('folder', 'video_id')) for x in entries):
                    raise ValueError('加工来源索引无效')
            if any(not isinstance(x, dict) or not isinstance(x.get('folder'), str)
                   or not isinstance(x.get('identities'), list)
                   or any(not isinstance(v, str) for v in x['identities']) for x in self.queue):
                raise ValueError('下载队列无效')
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            self.load_error = '工作区索引读取失败，请从历史批次重新打开；原文件保留'
            self.queue, self.inputs = [], {'md5': [], 'micro': []}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        save_json(self.path, {'schema': 1, 'batches': self.folders, 'last_batch': self.last_batch,
                             'download_queue': self.queue, 'processing_inputs': self.inputs})

    def register(self, batch):
        folder = str(batch.folder)
        if folder not in self.folders:
            self.folders.append(folder)
        self.last_batch = folder
        self.save()

    def create(self, text):
        result = []
        for drama in parse_dramas(text):
            batch = RecreationBatch.create(self.root, [drama])
            self.register(batch)
            result.append(batch)
        return result

    def import_files(self, paths):
        result = []
        for filename in paths:
            path = Path(filename)
            if path.suffix.lower() == '.json':
                batch = RecreationBatch.load(path.parent)
                self.register(batch)
                result.append(batch)
                continue
            info = parse_upload_drama_filename(path)
            if info:
                result.extend(self.create(info['drama_platform_id'] + '-' + info['drama_name']))
                continue
            if path.suffix.lower() == '.xlsx':
                from openpyxl import load_workbook
                from openpyxl.utils.exceptions import InvalidFileException
                try:
                    workbook = load_workbook(path, read_only=True, data_only=True)
                except (BadZipFile, InvalidFileException) as exc:
                    raise ValueError('Excel 文件无效，请检查文件格式') from exc
                try:
                    rows = list(workbook.active.values)
                finally:
                    workbook.close()
            elif path.suffix.lower() == '.csv':
                with path.open(encoding='utf-8-sig', newline='') as stream:
                    rows = list(csv.reader(stream))
            else:
                raise ValueError('请选择 ID-剧名.xlsx、剧目清单 CSV/XLSX 或 recreation.json')
            if not rows:
                raise ValueError('剧目清单为空')
            headers = [str(x or '').strip() for x in rows[0]]
            id_col = next((i for i, x in enumerate(headers) if x in {'剧目ID', '短剧ID', '剧目 ID', '短剧 ID'}), None)
            name_col = next((i for i, x in enumerate(headers) if x in {'剧名', '短剧名称'}), None)
            if id_col is None:
                raise ValueError('清单需包含“剧目ID”或使用“ID-剧名.xlsx”文件名')
            lines = []
            for row in rows[1:]:
                if id_col >= len(row) or row[id_col] in (None, ''):
                    continue
                value = row[id_col]
                identity = str(int(value)) if isinstance(value, (int, float)) and int(value) == value else str(value).strip()
                name = str(row[name_col] or '').strip() if name_col is not None and name_col < len(row) else ''
                lines.append(identity + ('-' + name if name else ''))
            result.extend(self.create('\n'.join(lines)))
        return result

    def enqueue(self, folder, identities):
        job = {'folder': str(Path(folder).resolve()), 'identities': list(dict.fromkeys(identities))}
        if job not in self.queue:
            self.queue.append(job)
        self.save()

    def add_inputs(self, mode, folder, identities):
        entries = self.inputs[mode]
        for identity in identities:
            ref = {'folder': str(Path(folder).resolve()), 'video_id': identity}
            if ref not in entries:
                entries.append(ref)
        self.save()

    def resolve_inputs(self, mode):
        batches, result = {}, []
        for ref in self.inputs[mode]:
            folder = ref['folder']
            if folder not in batches:
                batches[folder] = RecreationBatch.load(folder, recover_interrupted=False)
            item = batches[folder].source_by_id(ref['video_id'])
            result.append({**item, 'batch_folder': folder})
        return result
