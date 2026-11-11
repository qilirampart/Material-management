"""Independent recreation workspace; shares browser login, not task state."""
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QPlainTextEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QFileDialog, QInputDialog,
)
from src.batch import save_json
from src.desktop_widgets import PlatformPage, button, title, local_open
from src.paths import APP_RUNTIME_ROOT
from src.recreation import RecreationBatch, parse_dramas
from src.task_input import local_files_to_rows
from src.ui_design import card, label
from src.variant_dialog import VariantDialog


class RecreationPage(QWidget):
    def __init__(self, config, *, restore=True):
        super().__init__()
        self.output_root = Path(config['output_root'])
        self.preferences_path = Path(config.get('recreation_preferences_path',
                                                APP_RUNTIME_ROOT / 'recreation-workspace.json'))
        self.batch = None
        self.variant_dialog = None
        outer = QVBoxLayout(self)
        outer.addWidget(title('素材再创作'))
        self.summary = label('独立批次 · 共用智投登录')
        outer.addWidget(self.summary)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        collect = QWidget()
        box = QVBoxLayout(collect)
        intro, form = card('选择剧目')
        self.drama_input = QPlainTextEdit()
        self.drama_input.setPlaceholderText('每行填写剧目 ID 或 ID-剧名\n41000329324-垃圾桶里捡到爹')
        self.drama_input.setMaximumHeight(100)
        form.addWidget(self.drama_input)
        actions = QHBoxLayout()
        actions.addWidget(button('创建批次', self.create_batch, True))
        actions.addWidget(button('历史批次', self.open_batch))
        actions.addWidget(button('打开智投登录', self.open_login))
        actions.addStretch()
        form.addLayout(actions)
        box.addWidget(intro)
        row = QHBoxLayout()
        self.drama_selector = QComboBox()
        row.addWidget(self.drama_selector, 1)
        self.query_button = button('查询并下载', lambda: None, True)
        self.query_button.setEnabled(False)
        self.query_button.setToolTip('等待登录后验证平台的查询、分页和下载入口')
        row.addWidget(self.query_button)
        row.addWidget(button('导入已有素材', self.import_sources))
        box.addLayout(row)
        self.collection_status = label('自动采集待网页验证 · 筛选“二创”与“精剪原片”')
        box.addWidget(self.collection_status)
        self.source_table = self._table(['剧目', '素材', '下载状态', '本地路径'])
        box.addWidget(self.source_table, 1)
        box.addWidget(button('加工选中素材 →', self.process_selected, True))
        self.tabs.addTab(collect, '1 采集下载')
        processing = QWidget()
        box = QVBoxLayout(processing)
        box.addWidget(label('选中来源生成样片或批量加工；原视频保持不变'))
        row = QHBoxLayout()
        row.addWidget(button('加工选中来源', self.process_selected, True))
        row.addWidget(button('打开本批次目录', self.open_folder))
        row.addStretch()
        box.addLayout(row)
        self.output_table = self._table(['剧目', '处理方式', '成品', '码率 / 大小'])
        box.addWidget(self.output_table, 1)
        row = QHBoxLayout()
        row.addWidget(button('播放选中成品', self.play_selected))
        self.upload_drama = QComboBox()
        row.addWidget(self.upload_drama, 1)
        row.addWidget(button('准备本剧上传 →', self.prepare_upload, True))
        box.addLayout(row)
        self.tabs.addTab(processing, '2 加工预览')
        isolated_config = dict(config)
        isolated_config['upload_preferences_path'] = str(APP_RUNTIME_ROOT / 'recreation-upload-preferences.json')
        isolated_config['developer_edge_mode'] = False
        self.platform = PlatformPage(isolated_config, workflow='recreation')
        self.tabs.addTab(self.platform, '3 上传准备')
        self.message = label('先创建批次或打开历史批次')
        outer.addWidget(self.message)
        if restore:
            self.restore_last_batch()

    @staticmethod
    def _table(headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().hide()
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        table.setAlternatingRowColors(True)
        return table

    def active_background_tasks(self):
        tasks = self.platform.active_background_tasks()
        if self.variant_dialog and self.variant_dialog.task and self.variant_dialog.task.isRunning():
            tasks.append(self.variant_dialog.task)
        return tasks

    def create_batch(self):
        if self.active_background_tasks():
            self.message.setText('请先完成当前任务')
            return
        try:
            self.batch = RecreationBatch.create(self.output_root, parse_dramas(self.drama_input.toPlainText()))
            self.remember_batch()
            self.load_batch_view()
            self.message.setText('批次已创建，可导入已有素材；自动采集待网页验证')
        except (ValueError, OSError) as exc:
            self.message.setText(str(exc))

    def remember_batch(self):
        self.preferences_path.parent.mkdir(parents=True, exist_ok=True)
        save_json(self.preferences_path, {'last_batch': str(self.batch.folder)})

    def restore_last_batch(self):
        try:
            saved = json.loads(self.preferences_path.read_text(encoding='utf-8'))
            self.batch = RecreationBatch.load(saved['last_batch'])
        except (OSError, ValueError, KeyError):
            return
        self.load_batch_view()

    def open_batch(self):
        if self.active_background_tasks():
            self.message.setText('请先完成当前任务')
            return
        folder = QFileDialog.getExistingDirectory(self, '打开再创作批次', str(self.output_root / '素材再创作'))
        if not folder:
            return
        try:
            self.batch = RecreationBatch.load(folder)
            self.remember_batch()
            self.load_batch_view()
        except (ValueError, OSError) as exc:
            self.message.setText(str(exc))

    def load_batch_view(self):
        self.summary.setText('当前批次：' + self.batch.folder.name + ' · 独立于原素材任务')
        self.drama_input.setPlainText('\n'.join(x['id'] + ('-' + x['name'] if x['name'] else '')
                                               for x in self.batch.state['dramas']))
        for selector in (self.drama_selector, self.upload_drama):
            selector.clear()
            for drama in self.batch.state['dramas']:
                selector.addItem(drama['id'] + ' · ' + (drama['name'] or '待确认剧名'), drama['id'])
        self.refresh_sources()
        self.refresh_outputs()
        self.platform.set_materials([], {}, {}, set(), self.batch.folder)

    def open_login(self):
        self.tabs.setCurrentIndex(2)
        if self.platform.browser is None:
            self.platform.open_platform()

    def import_sources(self):
        if not self.batch:
            self.message.setText('请先创建批次')
            return
        drama = next(x for x in self.batch.state['dramas'] if x['id'] == self.drama_selector.currentData())
        if not drama['name']:
            name, ok = QInputDialog.getText(self, '确认剧名', '剧名')
            if not ok or not name.strip():
                return
            drama['name'] = name.strip()
        paths, _ = QFileDialog.getOpenFileNames(self, '导入已有素材', '', '视频 (*.mp4 *.mov *.mkv *.avi *.webm)')
        if paths:
            try:
                self.batch.add_local_sources(paths, drama)
                for selector in (self.drama_selector, self.upload_drama):
                    index = selector.findData(drama['id'])
                    selector.setItemText(index, drama['id'] + ' · ' + drama['name'])
                self.refresh_sources()
                self.message.setText(f'已加入本剧素材，共 {len(self.batch.state["sources"])} 条来源')
            except (OSError, ValueError) as exc:
                self.message.setText(str(exc))

    def refresh_sources(self):
        sources = self.batch.state['sources'] if self.batch else []
        self.source_table.setRowCount(len(sources))
        for index, item in enumerate(sources):
            status = '本地可用' if item.get('path') and Path(item['path']).is_file() else {
                'pending': '待下载', 'downloading': '下载中', 'failed': '下载失败',
                'downloaded': '文件缺失', 'local': '文件缺失',
            }.get(item.get('download_status'), '待下载')
            for column, value in enumerate((item['drama'], item['name'],
                                           status, item.get('path', ''))):
                self.source_table.setItem(index, column, QTableWidgetItem(value))

    def refresh_outputs(self):
        outputs = self.batch.state['outputs'] if self.batch else []
        self.output_table.setRowCount(len(outputs))
        for index, item in enumerate(outputs):
            meta = item['metadata']
            info = f"{meta.get('video_bitrate_bps', 0) / 1000:.0f} kbps · {meta.get('file_size_bytes', 0) / 1048576:.1f} MB"
            for column, value in enumerate((item['drama'], '微创新' if item['mode'] == 'micro' else '改 MD5',
                                           Path(item['path']).name, info)):
                self.output_table.setItem(index, column, QTableWidgetItem(value))

    def process_selected(self):
        if not self.batch or self.active_background_tasks():
            return
        indices = sorted({x.row() for x in self.source_table.selectionModel().selectedRows()})
        sources = [self.batch.state['sources'][i] for i in indices]
        available = [x for x in sources if x.get('path') and Path(x['path']).is_file()]
        if len(available) != len(sources) or not available:
            self.message.setText('请在采集下载页选中本地可用的来源素材')
            self.tabs.setCurrentIndex(0)
            return
        dialog = VariantDialog(available, self.batch.folder / '加工成品', self)
        self.variant_dialog = dialog
        dialog.import_button.setText('返回成品列表')
        dialog.result_ready.connect(self.receive_outputs)
        dialog.exec()
        self.variant_dialog = None
        dialog.deleteLater()
        self.refresh_outputs()
        self.tabs.setCurrentIndex(1)

    def receive_outputs(self, result):
        self.batch.add_outputs(result['outputs'])
        self.refresh_outputs()

    def prepare_upload(self):
        if not self.batch:
            return
        drama_id = self.upload_drama.currentData()
        indices = sorted({x.row() for x in self.output_table.selectionModel().selectedRows()})
        outputs = [self.batch.state['outputs'][i] for i in indices
                   if self.batch.state['outputs'][i].get('upload_drama_info', {}).get('drama_platform_id') == drama_id]
        if not outputs:
            self.message.setText('请选择成品，并选择相应的上传剧目')
            return
        rows, records = [], {}
        for output in outputs:
            try:
                row = local_files_to_rows([output['path']])[0]
            except ValueError as exc:
                self.message.setText(str(exc))
                return
            row.update(processing_mode=output['mode'], upload_drama_info=output['upload_drama_info'])
            row['source']['剧名'] = output['drama']
            rows.append(row)
            records[row['video_id']] = {
                'video_path': output['path'], 'metadata': output['metadata'], 'download': '已下载',
                'status': 'review_required', 'reason': '仅下载，未调用模型',
                'processing_mode': output['mode'],
            }
        self.platform.set_materials(rows, records, {}, set(records), self.batch.folder)
        self.tabs.setCurrentIndex(2)
        self.message.setText(f'本剧已选 {len(rows)} 个成品 · 尚未进行内容检测 · 可见范围：客户端二组')

    def play_selected(self):
        if not self.batch:
            return
        indices = self.output_table.selectionModel().selectedRows()
        if indices:
            local_open(self.batch.state['outputs'][indices[0].row()]['path'])

    def open_folder(self):
        if self.batch:
            local_open(self.batch.folder)
