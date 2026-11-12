"""Independent recreation workspace; shares browser login, not task state."""
import json
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QDate, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QPlainTextEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QFileDialog, QInputDialog, QDateEdit, QProgressBar, QMessageBox,
)
from src.batch import save_json
from src.desktop_widgets import PlatformPage, button, title, local_open
from src.paths import APP_RUNTIME_ROOT
from src.recreation import RecreationBatch, parse_dramas
from src.task_input import local_files_to_rows
from src.ui_design import card, label, Background
from src.variant_dialog import VariantDialog
from src.edge_cdp import find_page_ws_url
from src.recreation_platform import (
    PlatformMaterialClient, RecreationPlatformError, collect_platform_materials, download_platform_materials,
)


class RecreationPage(QWidget):
    task_finished = Signal()
    def __init__(self, config, *, restore=True):
        super().__init__()
        self.output_root = Path(config['output_root'])
        self.preferences_path = Path(config.get('recreation_preferences_path',
                                                APP_RUNTIME_ROOT / 'recreation-workspace.json'))
        self.batch = None
        self.variant_dialog = None
        self.collection_task = None
        self.collection_stop = threading.Event()
        outer = QVBoxLayout(self)
        outer.addWidget(title('素材再创作'))
        self.summary = label('独立批次 · 共用智投登录')
        outer.addWidget(self.summary)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        collect = QWidget()
        box = QVBoxLayout(collect)
        intro, form = card('选择剧目')
        self.input_card = intro
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
        dates = QHBoxLayout()
        dates.addWidget(label('上传日期'))
        self.date_start = QDateEdit(QDate(2014, 1, 1))
        self.date_end = QDateEdit(QDate.currentDate())
        for edit in (self.date_start, self.date_end):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat('yyyy-MM-dd')
            edit.setMinimumWidth(145)
            dates.addWidget(edit)
        dates.addStretch()
        box.addLayout(dates)
        row = QHBoxLayout()
        self.drama_selector = QComboBox()
        row.addWidget(self.drama_selector, 1)
        self.query_button = button('查询本批次素材', self.query_materials, True)
        self.query_button.setToolTip('遍历本批次所有剧目的“二创”和“精剪原片”全部分页')
        row.addWidget(self.query_button)
        self.import_button = button('导入已有素材', self.import_sources)
        row.addWidget(self.import_button)
        box.addLayout(row)
        self.collection_status = label('查询“二创”与“精剪原片” · 默认覆盖历史上传日期')
        box.addWidget(self.collection_status)
        self.collection_bar = QProgressBar()
        self.collection_bar.setRange(0, 1)
        self.collection_bar.setValue(0)
        box.addWidget(self.collection_bar)
        self.source_table = self._table(['剧目', '素材', '下载状态', '本地路径'])
        self.source_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.source_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.source_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Interactive)
        self.source_table.setColumnWidth(3, 230)
        box.addWidget(self.source_table, 1)
        downloads = QHBoxLayout()
        self.download_button = button('下载全部待处理素材', lambda: self.start_downloads(False))
        self.download_selected_button = button('下载选中素材', lambda: self.start_downloads(True))
        self.stop_button = button('停止', self.stop_collection)
        self.stop_button.setEnabled(False)
        for control in (self.download_button, self.download_selected_button, self.stop_button):
            downloads.addWidget(control)
        downloads.addStretch()
        downloads.addWidget(button('加工选中素材 →', self.process_selected, True))
        box.addLayout(downloads)
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
        if self.collection_task and self.collection_task.isRunning():
            tasks.append(self.collection_task)
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
            self.message.setText('批次已创建，查询素材后可下载')
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
        dates = self.batch.state.get('query_dates', {})
        for key, edit in (('start', self.date_start), ('end', self.date_end)):
            if dates.get(key):
                edit.setDate(QDate.fromString(dates[key], 'yyyy-MM-dd'))

    def query_materials(self):
        if self.active_background_tasks():
            self.message.setText('请先完成当前任务')
            return
        if not self.batch:
            self.create_batch()
        if not self.batch:
            return
        try:
            proposed = parse_dramas(self.drama_input.toPlainText())
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        if [x['id'] for x in proposed] != [x['id'] for x in self.batch.state['dramas']]:
            self.message.setText('剧目已变更，请先创建新批次')
            return
        start = self.date_start.date().toString('yyyy-MM-dd')
        end = self.date_end.date().toString('yyyy-MM-dd')
        if start > end:
            self.message.setText('开始日期不能晚于结束日期')
            return
        self._start_browser_task('query', start_date=start, end_date=end)

    def start_downloads(self, selected_only):
        if not self.batch or self.active_background_tasks():
            return
        indices = {x.row() for x in self.source_table.selectionModel().selectedRows()}
        items = [x for i, x in enumerate(self.batch.state['sources']) if x.get('source_material_id')
                 and (not selected_only or i in indices)]
        pending = [x for x in items if not (x.get('path') and Path(x['path']).is_file()
                                            and x['download_status'] == 'downloaded')]
        if not pending:
            self.message.setText('没有待下载素材；可先查询或选择未完成项')
            return
        if len(pending) > 20 and QMessageBox.question(
                self, '确认批量下载', f'将下载 {len(pending)} 条视频，已成功项会跳过。继续？',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self._start_browser_task('download', identities=[x['video_id'] for x in pending])

    def _start_browser_task(self, operation, **kwargs):
        if self.platform.browser is None:
            self.platform.open_platform()
        if self.platform.browser is None:
            self.message.setText('请先打开智投登录')
            return
        target_id = self.platform.browser.page().devToolsId()
        if not target_id:
            self.message.setText('平台页面正在启动，请稍后重试')
            return
        port = self.platform.internal_browser_debug_port
        url = self.platform.config.get('platform_url') or self.platform.address.text()
        folder = self.batch.folder
        self.collection_stop.clear()
        task = None
        def execute():
            ws_url = find_page_ws_url(url, port, target_id=target_id)
            client = PlatformMaterialClient(ws_url, should_stop=self.collection_stop.is_set,
                                            on_wait=task.progress.emit)
            client.ensure_ready()
            batch = RecreationBatch.load(folder)
            common = {'progress': task.progress.emit, 'should_stop': self.collection_stop.is_set}
            try:
                if operation == 'query':
                    return collect_platform_materials(batch, client, **kwargs, **common)
                return download_platform_materials(batch, client, **kwargs, **common)
            except ValueError as exc:
                raise RecreationPlatformError(str(exc)) from None
        task = Background(execute, self)
        self.collection_task = task
        task.progress.connect(self.show_collection_progress)
        task.result.connect(self.collection_result)
        task.failed.connect(self.collection_failed)
        task.finished.connect(self.collection_finished)
        self._set_collection_busy(True)
        self.collection_status.setText('正在连接智投素材管理…')
        self.collection_bar.setRange(0, 0)
        self.collection_bar.setFormat('%p%')
        task.start()

    def _set_collection_busy(self, busy):
        for control in (self.input_card, self.query_button, self.import_button, self.drama_selector,
                        self.download_button, self.download_selected_button, self.date_start, self.date_end):
            control.setEnabled(not busy)
        self.stop_button.setEnabled(busy)

    def _sync_collection_state(self):
        self.batch = RecreationBatch.load(self.batch.folder, recover_interrupted=False)
        self.refresh_sources()
        for drama in self.batch.state['dramas']:
            for selector in (self.drama_selector, self.upload_drama):
                index = selector.findData(drama['id'])
                if index >= 0:
                    selector.setItemText(index, drama['id'] + ' · ' + drama['name'])

    def show_collection_progress(self, event):
        phase = event['phase']
        if phase == 'rate_limited':
            self.collection_status.setText(f"平台限流，等待 {event['seconds']} 秒后重试…")
            return
        if phase == 'lookup':
            text = f"查找剧目 {event['index']} / {event['total']} · {event['drama_id']}"
        elif phase == 'page':
            text = f"{event['drama']} · {event['keyword']} 第 {event['page']} 页 · 已收集 {event['matched']} 条"
        else:
            names = {'resolving': '读取原始视频地址', 'validating': '校验本地视频',
                     'downloaded': '下载完成', 'failed': '下载失败', 'downloading': '下载中'}
            text = f"{event['index']} / {event['total']} · {event['drama']} · {names.get(phase, phase)}"
            if event.get('message'):
                text += ' · ' + event['message']
            if phase == 'downloading':
                received, size = event['bytes'], event['size']
                amount = f"{received / 1048576:.1f}" + (f" / {size / 1048576:.1f}" if size else '')
                text += f" · {amount} MB · {event['speed'] / 1048576:.1f} MB/s"
                self.collection_bar.setRange(0, 1000 if size else 0)
                self.collection_bar.setValue(int(received / size * 1000) if size else 0)
                if event.get('retry'):
                    text = f"{event['index']} / {event['total']} · {event['drama']} · 连接中断，正在重试 {event['retry']} / 2…"
            else:
                self.collection_bar.setRange(0, event['total'])
                self.collection_bar.setValue(event['index'] if phase in {'downloaded', 'failed'} else event['index'] - 1)
            if phase not in {'downloaded', 'failed'}:
                for row, item in enumerate(self.batch.state['sources']):
                    if item['video_id'] == event['video_id']:
                        self.source_table.item(row, 2).setText(names.get(phase, phase))
                        break
        self.collection_status.setText(text)
        if phase in {'page', 'downloaded', 'failed'}:
            self._sync_collection_state()

    def collection_result(self, result):
        self._sync_collection_state()
        if 'count' in result:
            message = f"已找到 {result['count']} 条素材，可以下载全部或选中项"
        else:
            message = f"完成 {result['completed']} 条 · 失败 {result['failed']} 条 · 跳过 {result['skipped']} 条"
        self.message.setText(message + (' · 已停止' if result.get('stopped') else ''))

    def collection_failed(self, message):
        self.message.setText(message)
        self._sync_collection_state()

    def collection_finished(self):
        self._set_collection_busy(False)
        self.collection_bar.setRange(0, 1)
        self.collection_bar.setValue(1)
        self.collection_bar.setFormat('本轮已结束')
        self.collection_status.setText('本轮任务已结束；进度和文件已保留')
        self.task_finished.emit()

    def stop_collection(self):
        self.collection_stop.set()
        self.stop_button.setEnabled(False)
        self.collection_status.setText('正在停止当前请求；已完成的文件和记录保留…')

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
                self.source_table.item(index, column).setToolTip(item.get('download_error') or value)

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
