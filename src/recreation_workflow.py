"""Six-stage recreation UI. Reuses the established batch and platform engines."""
import threading
import sqlite3
from datetime import date
from uuid import uuid4
from collections import defaultdict
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QListWidgetItem, QDialog, QPlainTextEdit, QDialogButtonBox, QFileDialog,
    QComboBox, QTableWidgetItem, QMessageBox, QFormLayout, QLineEdit, QInputDialog)
from src.recreation_page import RecreationPage
from src.recreation_workspace import RecreationWorkspace
from src.recreation_cleanup_page import CleanupPage
from src.recreation_processing import ProcessingWorkbench
from src.recreation_schedule_ui import ScheduleController
from src.recreation import RecreationBatch
from src.recovery_dialog import RecoveryDialog
from src.material_name_filter import NameFilter
from src.recreation_platform import RecreationPlatformError
from src.recreation_upload import upload_files, upload_script, record_upload, reconcile_upload, UploadNotStarted
from src.recreation_submit import submit_uploaded_batch, close_submission_receipt, SubmitNotStarted
from src.ui_design import card, label, btn, Background
from src.task_input import local_files_to_rows
from src.upload import remember_default_director, recreation_upload_namespace, reserve_recreation_upload_sequences
from src.edge_cdp import find_page_ws_url, evaluate_edge_page


class RecreationWorkflowPage(RecreationPage):
    def __init__(self, config, *, restore=True):
        config = dict(config)
        self.speed_config = config
        self.task_notice = lambda *args,**kwargs: None
        self.legacy_download_active = threading.Event()
        self.legacy_download_generation = 0
        config['platform_url'] = config.get('platform_url') or 'https://market.wuread.cn/market-admin/'
        super().__init__(config, restore=False)
        self.setObjectName('recreationWorkflow')
        self.setStyleSheet('QWidget#recreationWorkflow { background:#F4F6F8; }'
            'QListWidget::item { padding:12px 6px; border-bottom:1px solid #E5EBEC; }'
            'QListWidget::item:selected { background:#E6F3F0; color:#0F5C55; }'
            'QProgressBar::chunk { background:#0F766E; }')
        self.workspace = RecreationWorkspace(self.preferences_path, self.output_root)
        if not restore:
            self.workspace.folders, self.workspace.queue = [], []
            self.workspace.inputs = {'md5': [], 'micro': []}
        self.pending_import = None
        self.queue_running = False
        self.queue_stopped = False
        self.job_failed = False
        self.queue_steps_left = 0
        self.queue_completed = self.queue_failed = 0
        self.queue_pause_reason = ''
        self.queue_remaining_ids = None
        self.upload_task, self.upload_busy = None, False
        self.upload_stop_event = threading.Event()
        self.upload_groups, self.catalog = [], []
        self.recovery_dialog=None
        self.auto_upload_pending = False
        self.current_upload = None
        self.upload_attempt = None
        self.upload_needs_review = False
        self.auto_continue_group = None
        self.upload_continue_timer = QTimer(self)
        self.upload_continue_timer.setSingleShot(True)
        self.upload_continue_timer.timeout.connect(self.resume_auto_upload)
        self.upload_total = 0
        self.upload_run_submitted = 0
        self.upload_round_id = ''
        collect, old_outputs = self.tabs.widget(0), self.tabs.widget(1)
        while self.tabs.count():
            self.tabs.removeTab(0)
        self.platform.setParent(self)
        self.platform.hide()
        login = QWidget()
        layout = QVBoxLayout(login)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.platform.browser_card)
        self.platform.browser_card.show()
        self.tabs.addTab(login, '01  登录点众智投')
        self.input_card.hide()
        download = QWidget()
        body = QHBoxLayout(download)
        body.setContentsMargins(0, 0, 0, 0)
        sidebar, left = card('下载批次')
        sidebar.setFixedWidth(260)
        left.addWidget(btn('+ 批量导入剧目 ID', self.new_batches, True))
        left.addWidget(btn('导入批次文件…', self.import_batch_files))
        left.addWidget(btn('打开历史批次…', self.open_batch))
        self.batch_search = QLineEdit()
        self.batch_search.setPlaceholderText('搜索剧名 / 剧目 ID / 批次号')
        left.addWidget(self.batch_search)
        self.batch_search_hint = label('')
        self.batch_search_hint.hide()
        left.addWidget(self.batch_search_hint)
        self.batch_list = QListWidget()
        self.batch_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left.addWidget(self.batch_list, 1)
        self.queue_button = btn('将勾选批次加入下载队列', self.enqueue_batches)
        self.resume_button = btn('继续下载队列', self.resume_download_queue)
        left.addWidget(self.queue_button)
        left.addWidget(self.resume_button)
        self.queue_summary = label('下载队列 0 个批次')
        left.addWidget(self.queue_summary)
        self.cleanup_button = btn('清理勾选批次…', self.manage_batches)
        left.addWidget(self.cleanup_button)
        body.addWidget(sidebar)
        # Existing dates, query controls, checks and transfer progress stay intact.
        self.batch_heading = label('选择或导入一个批次', 'section')
        download_heading = QHBoxLayout()
        download_heading.addWidget(self.batch_heading, 1)
        collect.layout().insertLayout(0, download_heading)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(btn('导入改 MD5 →', lambda: self.open_processing_import('md5', from_download=True)))
        footer.addWidget(btn('导入微创新 →', lambda: self.open_processing_import('micro', from_download=True)))
        collect.layout().addLayout(footer)
        for b in collect.findChildren(type(self.query_button)):
            if b.text() == '加工勾选素材 →':
                b.hide()
        body.addWidget(collect, 1)
        collect.show()
        self.tabs.addTab(download, '02  视频下载')
        self.md5 = ProcessingWorkbench(self, 'md5')
        self.micro = ProcessingWorkbench(self, 'micro')
        self.tabs.addTab(self.md5, '03  改 MD5')
        self.tabs.addTab(self.micro, '04  微创新')
        for panel in (self.md5, self.micro):
            panel.finished.connect(self.processing_finished)
            panel.uploader.setText(self.platform.uploader_initials.text())
        upload = QWidget()
        upload_box = QHBoxLayout(upload)
        upload_box.setContentsMargins(0, 0, 0, 0)
        products, box = card('选择待上传成品')
        self.output_filter = QComboBox()
        self.output_filter.addItem('全部处理来源', '')
        self.output_filter.addItem('改 MD5', 'md5')
        self.output_filter.addItem('微创新', 'micro')
        box.addWidget(self.output_filter)
        filters = QHBoxLayout()
        self.output_search = QLineEdit()
        self.output_search.setPlaceholderText('搜索剧名、剧目 ID 或加工批次')
        filters.addWidget(self.output_search, 1)
        self.output_state = QComboBox()
        for title, key in [('待上传', 'ready'), ('已上传文件', 'uploaded'), ('已提交审核', 'submitted'),
                           ('待核对', 'review'), ('提交待核对', 'submission_review'),
                           ('文件缺失', 'missing'), ('全部状态', '')]:
            self.output_state.addItem(title, key)
        filters.addWidget(self.output_state)
        box.addLayout(filters)
        box.addLayout(self._selection_bar_reparent(self.output_table))
        box.addWidget(self.output_table, 1)
        self.output_table.setHorizontalHeaderLabels(['勾选', '剧目', '处理来源', '成品', '文件状态'])
        box.addWidget(label('按剧目分组，每批最多 50 条。'))
        controls = QHBoxLayout()
        controls.addWidget(btn('播放勾选成品', self.play_selected))
        controls.addWidget(btn('刷新成品列表', self.refresh_outputs))
        self.recover_button=btn('找回加工成品…',self.recover_products)
        controls.addWidget(self.recover_button)
        controls.addWidget(btn('核对平台结果…', self.review_upload_records))
        controls.addStretch()
        box.addLayout(controls)
        upload_box.addWidget(products, 1)
        self.platform.preparation_card.hide()
        settings, prep = card('上传设置')
        settings.setFixedWidth(340)
        upload_box.addWidget(settings)
        prep.addWidget(label('共用第 1 步登录 · 客户端二组'))
        fields = QFormLayout()
        director_row = QHBoxLayout()
        self.upload_director = QLineEdit()
        self.refresh_director_hint()
        director_row.addWidget(self.upload_director, 1)
        director_row.addWidget(btn('设默认…', self.edit_default_director))
        fields.addRow('编导', director_row)
        fields.addRow('上传人缩写', self.platform.uploader_initials)
        fields.addRow('可见范围', label('客户端二组'))
        self.submit_mode = QComboBox()
        self.submit_mode.addItem('手动提交（默认）', 'manual')
        self.submit_mode.addItem('本轮自动提交审核', 'auto')
        fields.addRow('提交方式', self.submit_mode)
        prep.addLayout(fields)
        self.submit_hint = label('助手上传文件，你在智投确认提交。')
        self.submit_hint.setWordWrap(True)
        self.submit_mode.currentIndexChanged.connect(self.update_submit_hint)
        prep.addWidget(self.submit_hint)
        prep.addStretch()
        self.upload_status = label('待开始 · 没有正在上传的文件')
        prep.addWidget(self.upload_status)
        self.upload_batch_summary = label('尚未建立上传队列', 'summary')
        prep.addWidget(self.upload_batch_summary)
        self.upload_batch_files = QListWidget()
        self.upload_batch_files.setMinimumHeight(106)
        self.upload_batch_files.setMaximumHeight(154)
        self.upload_batch_files.setStyleSheet('QListWidget::item { padding: 4px 6px; }')
        prep.addWidget(self.upload_batch_files)
        # Replace the manual-only action with explicit auto-upload controls; the
        # original component remains unchanged for the original workflow.
        self.auto_button = btn('建立待传队列', self.begin_upload, True)
        self.next_upload_button = btn('继续下一批（当前表单已处理）', self.continue_upload, True)
        self.next_upload_button.setEnabled(False)
        prep.addWidget(self.auto_button)
        prep.addWidget(self.next_upload_button)
        self.remove_upload_button = btn('移出选中文件', self.remove_queued_upload)
        self.cancel_upload_button = btn('结束队列…', self.cancel_upload_queue)
        queue_actions = QHBoxLayout()
        queue_actions.addWidget(self.remove_upload_button)
        queue_actions.addWidget(self.cancel_upload_button)
        prep.addLayout(queue_actions)
        platform_actions = QHBoxLayout()
        pause = btn('暂停后续上传', self.pause_upload)
        pause.setToolTip('当前已开始的传输会等平台返回结果')
        platform_actions.addWidget(pause)
        platform_actions.addWidget(btn('查看智投页面', self.open_login))
        prep.addLayout(platform_actions)
        self.platform.fill_button.hide()
        self.platform.configure_button.setText('配置编导与上传人')
        self.tabs.addTab(upload, '05  自动上传')
        self.file_cleanup = CleanupPage(self)
        self.tabs.addTab(self.file_cleanup, '06  文件清理')
        # Kept as the base controller's compatibility selector; the new upload
        # catalog is cross-batch and does not display this old single-drama UI.
        self.upload_drama.setParent(self)
        self.upload_drama.hide()
        self.tabs.tabBar().hide()
        self.tabs.setStyleSheet('QTabWidget::pane { border:0; }')
        navigation = QHBoxLayout()
        self.step_buttons = []
        for i, text in enumerate(('01  登录点众智投', '02  视频下载', '03  改 MD5', '04  微创新', '05  自动上传', '06  文件清理')):
            control = btn(text, lambda checked=False, index=i: self.tabs.setCurrentIndex(index))
            control.setCheckable(True)
            control.setStyleSheet('QPushButton { text-align:left; padding:12px; }'
                                 'QPushButton:checked { background:#E6F3F0; border:2px solid #0F766E; color:#0F766E; }')
            self.step_buttons.append(control)
            navigation.addWidget(control, 1)
        self.layout().insertLayout(2, navigation)
        self.tabs.currentChanged.connect(lambda current: [b.setChecked(i == current) for i, b in enumerate(self.step_buttons)])
        self.tabs.currentChanged.connect(lambda current: self.file_cleanup.refresh()
            if current == 5 and not self.work_in_progress() else None)
        old_outputs.deleteLater()
        self.output_filter.currentIndexChanged.connect(self.refresh_outputs)
        self.output_search.textChanged.connect(self.refresh_outputs)
        self.output_state.currentIndexChanged.connect(self.refresh_outputs)
        self.batch_list.currentRowChanged.connect(self.select_batch)
        self.batch_search.textChanged.connect(self.filter_batch_list)
        self.platform.staging_complete.connect(self.staging_for_upload_ready)
        self.platform.files_ready.connect(self.files_for_upload_ready)
        self.platform.operation_failed.connect(self.upload_failed)
        self.platform.activity_finished.connect(self.task_finished.emit)
        if restore:
            self.restore_last_batch()
        self.refresh_batch_list()
        for panel in (self.md5, self.micro):
            panel.refresh()
        self.refresh_outputs()
        self.refresh_upload_queue()
        self.schedule = ScheduleController(self, download_heading, active=restore)
        self.tabs.setCurrentIndex(1)
        if self.workspace.load_error:
            self.message.setText(self.workspace.load_error)

    def _selection_bar_reparent(self, table):
        # The old output toolbar belongs to the removed page. Rebuild once.
        return self._selection_bar(table)

    def active_background_tasks(self):
        tasks = super().active_background_tasks()
        for name in ('md5', 'micro'):
            panel = getattr(self, name, None)
            if panel and panel.task and panel.task.isRunning():
                tasks.append(panel.task)
        if getattr(self, 'upload_task', None) and self.upload_task.isRunning():
            tasks.append(self.upload_task)
        if getattr(self, 'cleanup_task', None) and self.cleanup_task.isRunning():
            tasks.append(self.cleanup_task)
        schedule = getattr(self, 'schedule', None)
        if schedule and schedule.worker and schedule.worker.isRunning():
            tasks.append(schedule.worker)
        return tasks

    def own_work_in_progress(self):
        return (super().own_work_in_progress() or getattr(self, 'upload_busy', False)
                or getattr(self, 'cleanup_busy', False)
                or getattr(getattr(self,'recovery_dialog',None),'busy',False)
                or getattr(getattr(self,'schedule',None),'working',False)
                or getattr(self, 'queue_running', False)
                or any(getattr(getattr(self, n, None), 'busy', False) for n in ('md5', 'micro')))

    def remember_batch(self):
        if not hasattr(self, 'workspace'):
            return
        try:
            self.workspace.path = self.preferences_path
            self.workspace.root = self.output_root
            self.workspace.register(self.batch)
        except OSError:
            self.message.setText('批次已保存，但工作区索引未能保存；下次请打开历史批次')

    def apply_config(self, config):
        # Only future batches use the new root. Existing jobs keep captured folders.
        self.speed_config = dict(config)
        self.output_root = Path(config['output_root'])
        self.workspace.root = self.output_root
        self.platform.config = dict(config)
        self.platform.address.setText(config.get('platform_url') or 'https://market.wuread.cn/market-admin/')
        self.file_cleanup.refresh()

    def only_md5_active(self):
        return (self.md5.busy and not self.micro.busy and not self.collection_busy and not self.queue_running
                and not self.upload_busy and not getattr(self,'cleanup_busy',False)
                and not self.schedule.working and not self.recovery_dialog
                and all(task is self.md5.task for task in self.active_background_tasks()))

    def md5_start_blocked(self):
        if self.own_work_in_progress():
            return True
        if not self.work_in_progress():
            return False
        return not (self.speed_config.get('md5_overlap') and
                    getattr(self,'only_legacy_download',lambda:False)())

    def restore_last_batch(self):
        folder = self.workspace.last_batch
        if folder:
            try:
                self.batch = RecreationBatch.load(folder)
                self.load_batch_view()
            except (OSError, ValueError):
                self.message.setText('上次批次不可用，请从历史批次重新打开')

    def refresh_batch_list(self):
        current = str(self.batch.folder) if self.batch else ''
        checked = {self.batch_list.item(i).data(Qt.UserRole) for i in range(self.batch_list.count())
                   if self.batch_list.item(i).checkState() == Qt.Checked}
        self.batch_list.blockSignals(True)
        self.batch_list.clear()
        active = -1
        for i, folder in enumerate(self.workspace.folders):
            try:
                batch = RecreationBatch.load(folder, recover_interrupted=False)
                dramas = batch.state['dramas']
                names = ' / '.join(x['name'] or x['id'] for x in dramas)
                details = ' / '.join(f"{x['id']} {x['name']}" for x in dramas)
                available = sum(bool(x.get('path')) and Path(x['path']).is_file() for x in batch.state['sources'])
                text = f'批次 {i+1:02d}\n{names[:12]}\n{names[12:24]}' if len(names) > 12 else f'批次 {i+1:02d}\n{names}'
                text += f"\n共 {len(batch.state['sources'])} 条 · 本地 {available} 条"
            except (OSError, ValueError):
                text = Path(folder).name + '\n批次不可用，请检查目录'
                details = '批次不可用'
            item = QListWidgetItem(text)
            item.setToolTip(f'{details}\n{folder}')
            item.setData(Qt.UserRole, folder)
            item.setData(Qt.UserRole + 1, f'{details} 批次 {i+1:02d} {Path(folder).name}'.casefold())
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if folder in checked else Qt.Unchecked)
            self.batch_list.addItem(item)
            if folder == current:
                active = i
        self.batch_list.setCurrentRow(active)
        self.filter_batch_list()
        self.batch_list.blockSignals(False)
        remaining_count = sum(len(job['identities']) for job in self.workspace.queue)
        state = '运行中' if self.queue_running else ('待继续' if self.workspace.queue else '无待处理任务')
        self.queue_summary.setText(f'下载队列 {len(self.workspace.queue)} 批 / {remaining_count} 条 · {state}')
        if getattr(self, 'queue_skipped', 0):
            self.queue_summary.setText(self.queue_summary.text() + f' · 已跳过 {self.queue_skipped} 个失效批次')

    def filter_batch_list(self, *_):
        terms = self.batch_search.text().casefold().split()
        visible = 0
        for row in range(self.batch_list.count()):
            item = self.batch_list.item(row)
            matches = all(term in item.data(Qt.UserRole + 1) for term in terms)
            item.setHidden(not matches)
            visible += matches
        self.batch_search_hint.setVisible(bool(terms))
        self.batch_search_hint.setText(f'找到 {visible} 个批次 · 操作仅限可见勾选项' if visible else '没有匹配的批次')

    def checked_batch_folders(self):
        return [item.data(Qt.UserRole) for i in range(self.batch_list.count())
                if not (item := self.batch_list.item(i)).isHidden() and item.checkState() == Qt.Checked]

    def select_batch(self, index):
        if index < 0:
            return
        folder = self.batch_list.item(index).data(Qt.UserRole)
        if self.work_in_progress():
            self.refresh_batch_list()
            self.message.setText('请先完成或停止当前任务，再切换批次')
            return
        try:
            self.batch = RecreationBatch.load(folder)
            self.load_batch_view()
            self.remember_batch()
        except (OSError, ValueError) as exc:
            self.message.setText(str(exc))

    def load_batch_view(self):
        super().load_batch_view()
        if hasattr(self, 'batch_heading'):
            self.batch_heading.setText(' / '.join(x['name'] or x['id'] for x in self.batch.state['dramas']))
            self.refresh_batch_list()
            self.message.setText('已载入独立批次，可获取素材或导入处理模块')

    def create_batch(self):
        if self.work_in_progress():
            self.message.setText('请先完成当前任务')
            return
        try:
            self.workspace.path = self.preferences_path
            self.workspace.root = self.output_root
            batches = self.workspace.create(self.drama_input.toPlainText(),include_name=self.include_name.text(),
                                            exclude_name=self.exclude_name.text())
            self.batch = batches[0]
            self.load_batch_view()
            self.remember_batch()
            self.message.setText(f'已建立 {len(batches)} 个独立剧目批次；选择批次后获取素材')
        except (ValueError, OSError) as exc:
            self.message.setText(str(exc))

    def new_batches(self):
        if self.work_in_progress():
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('批量导入剧目 ID')
        dialog.resize(600, 370)
        box = QVBoxLayout(dialog)
        box.addWidget(label('每行一个 ID 或 ID-剧名，每部剧建立独立批次', 'section'))
        text = QPlainTextEdit()
        text.setPlaceholderText('41000447945-捍卫婚前财产，我替自己撑腰\n41000329324-垃圾桶里捡到爹')
        box.addWidget(text)
        controls = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        controls.button(QDialogButtonBox.Ok).setText('创建独立批次')
        controls.accepted.connect(dialog.accept)
        controls.rejected.connect(dialog.reject)
        box.addWidget(controls)
        if dialog.exec() == QDialog.Accepted:
            self.drama_input.setPlainText(text.toPlainText())
            self.create_batch()

    def import_batch_files(self):
        if self.work_in_progress():
            return
        paths, _ = QFileDialog.getOpenFileNames(self, '导入剧目批次', '', '批次 (*.xlsx *.csv *.json)')
        if not paths:
            return
        try:
            self.workspace.path = self.preferences_path
            self.workspace.root = self.output_root
            batches = self.workspace.import_files(paths,include_name=self.include_name.text(),
                                                 exclude_name=self.exclude_name.text())
            if batches:
                self.batch = batches[0]
                self.load_batch_view()
            self.message.setText(f'已导入 {len(batches)} 个批次；表格按文件名或剧目 ID 列识别，获取后下载平台素材')
        except (OSError, ValueError) as exc:
            self.refresh_batch_list()
            self.message.setText('批次导入未全部完成：' + str(exc))

    def open_batch(self):
        super().open_batch()
        self.refresh_batch_list()

    def open_login(self):
        self.tabs.setCurrentIndex(0)
        if self.platform.browser is None:
            self.platform.open_platform()

    def enqueue_batches(self):
        if self.work_in_progress():
            return
        folders = self.checked_batch_folders()
        if not folders:
            self.message.setText('请先勾选可见批次，或点击“继续下载队列”恢复已有任务')
            return
        skipped = 0
        try:
            for folder in folders:
                try:
                    batch = RecreationBatch.load(folder, recover_interrupted=False)
                except (FileNotFoundError, ValueError):
                    skipped += 1
                    continue
                filters=NameFilter.for_batch(batch.state)
                ids = [x['video_id'] for x in batch.state['sources'] if x.get('source_material_id')
                    and not filters.reason(x['name'])
                    and not (x['download_status'] == 'downloaded' and x.get('path') and Path(x['path']).is_file())]
                if not ids:
                    skipped += 1
                    continue
                self.workspace.enqueue(batch.folder, ids)
        except OSError:
            self.message.setText('队列或批次记录读写失败；已保存的队列可在处理目录权限后继续')
            self.refresh_batch_list()
            return
        if self.workspace.queue:
            self.resume_download_queue(skipped=skipped)
        elif skipped:
            self.message.setText('没有可下载的任务：勾选的批次已完成、不可用或尚未查询素材')

    def resume_download_queue(self, checked=False, *, skipped=0):
        if self.work_in_progress() or not self.workspace.queue:
            return
        self.queue_running, self.queue_stopped = True, False
        self.queue_skipped = skipped
        self.queue_completed = self.queue_failed = 0
        self.queue_steps_left = len(self.workspace.queue)
        self.queue_pause_reason = ''
        self.start_next_download()

    def manage_batches(self):
        if self.work_in_progress():
            self.message.setText('请先完成或停止当前任务，再清理批次')
            return
        folders = self.checked_batch_folders()
        if not folders:
            self.message.setText('请在左侧勾选要清理的批次')
            return
        from src.recreation_cleanup import plan_cleanup
        dialog = QDialog(self)
        dialog.setWindowTitle('清理勾选批次')
        dialog.resize(780, 590)
        box = QVBoxLayout(dialog)
        box.addWidget(label(f'已勾选 {len(folders)} 个批次', 'section'))
        scope = QComboBox()
        for text, value in (('仅移出批次列表（不删除任何文件）', 'forget'),
                ('删除加工成品与配套封面（保留下载原片）', 'products'),
                ('删除下载原片（保留加工成品）', 'originals'),
                ('删除下载原片和加工成品（保留批次记录）', 'all')):
            scope.addItem(text, value)
        box.addWidget(scope)
        box.addWidget(label('文件删除不经过回收站。外部原文件、批次记录和上传暂存保留。'))
        preview = QPlainTextEdit(); preview.setReadOnly(True); box.addWidget(preview, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('继续确认…')
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        box.addWidget(buttons)
        planned = {}
        def update_preview():
            planned.clear()
            if scope.currentData() == 'forget':
                preview.setPlainText('移出这些批次及其下载队列、MD5／微创新来源引用。\n'
                    '原片、成品和批次记录都保留，可通过“打开历史批次…”再次添加。\n\n' + '\n'.join(folders))
                return
            planned.update(plan_cleanup(folders, scope.currentData()))
            lines = [f"将删除 {planned['files']} 个文件，合计 {planned['bytes']/1048576:.1f} MB（不等于实际释放空间）。",
                     f"另有 {planned['protected']} 条外部或不属于本批次的文件记录受保护，不删除。",
                     '已在外部删除的登记文件会同步为未下载／移出成品库。', '']
            lines.extend(planned['errors'])
            for batch in planned['batches']:
                lines.append(batch['folder'])
                for entry in batch['entries']:
                    lines.append('  ' + entry['path'])
                    if entry.get('cover', {}).get('signature'):
                        lines.append('  ' + entry['cover']['path'])
            preview.setPlainText('\n'.join(lines))
        scope.currentIndexChanged.connect(update_preview); update_preview()
        if dialog.exec() != QDialog.Accepted:
            return
        action = scope.currentData()
        question = ('仅移出所选批次及相关队列／加工引用？不会删除文件。' if action == 'forget' else
                    f"将永久删除预览中的 {planned['files']} 个文件，并同步相关记录。确定继续？")
        if QMessageBox.question(self, '确认清理范围', question, QMessageBox.Yes | QMessageBox.No,
                               QMessageBox.No) != QMessageBox.Yes:
            return
        if self.work_in_progress():
            self.message.setText('已有任务启动，本次清理未执行')
            return
        self.run_batch_cleanup(folders, action, dict(planned))

    def run_batch_cleanup(self, folders, action, plan):
        if self.upload_groups:
            self.message.setText('请先完成或结束本轮上传队列，再清理文件')
            self.file_cleanup.status.setText(self.message.text())
            return
        if self.work_in_progress():
            self.message.setText('当前任务尚未结束，未执行清理')
            return
        from src.recreation_cleanup import execute_cleanup
        self.cleanup_busy = True
        self.cleanup_button.setEnabled(False)
        self.file_cleanup.set_busy(True)
        self.message.setText('正在清理勾选批次，请等待文件和记录同步完成…')
        def execute():
            self.schedule.history.sync_batches(self.workspace.folders)
            if action == 'forget':
                self.workspace.forget_batches(folders)
                return {'deleted': 0, 'missing': 0, 'errors': [], 'protected': 0, 'forgotten': True}
            return execute_cleanup(plan, self.workspace)
        def completed(result):
            if self.batch and str(self.batch.folder) not in self.workspace.folders:
                self.batch = None
                self.source_table.setRowCount(0)
                self.batch_heading.setText('选择或导入一个批次')
            elif self.batch:
                try:
                    self.batch = RecreationBatch.load(self.batch.folder, recover_interrupted=False)
                    self.load_batch_view()
                except (OSError, ValueError):
                    self.batch = None; self.source_table.setRowCount(0)
            for panel in (self.md5, self.micro): panel.refresh()
            self.refresh_batch_list(); self.refresh_outputs()
            # Any pending upload plan was built from pre-cleanup paths.
            self.upload_groups = []; self.current_upload = None
            self.upload_needs_review = False
            self.refresh_upload_queue()
            self.platform.set_materials([], {}, {}, set(), None)
            self.upload_status.setText('清理已同步；需要上传时请重新勾选成品。平台中的未提交表单未改动。')
            summary = ('批次已移出，未删除文件。' if result.get('forgotten') else
                f"清理完成：删除 {result['deleted']} 个文件，同步 {result['missing']} 个已缺失文件；"
                f"保护 {result['protected']} 条外部文件记录。")
            self.message.setText(summary + (f" {len(result['errors'])} 项未完成，请查看详情。" if result['errors'] else ''))
            self.file_cleanup.refresh()
            self.file_cleanup.status.setText(self.message.text())
            if result['errors']:
                QMessageBox.warning(self, '清理未全部完成', summary + '\n\n' + '\n'.join(result['errors'][:12]))
        def finished():
            self.cleanup_busy = False
            self.cleanup_button.setEnabled(True)
            self.file_cleanup.set_busy(False)
            self.task_finished.emit()
        self.cleanup_task = Background(execute, self)
        self.cleanup_task.result.connect(completed)
        def failed(msg):
            self.message.setText('清理未完成：' + msg)
            self.file_cleanup.refresh()
            self.file_cleanup.status.setText(self.message.text())
        self.cleanup_task.failed.connect(failed)
        self.cleanup_task.finished.connect(finished)
        self.cleanup_task.start()

    def start_next_download(self):
        if not self.queue_running:
            return
        if self.queue_stopped and self.workspace.queue:
            self.pause_download_round('已手动暂停；点击“继续下载队列”下载剩余项')
            return
        if self.queue_stopped or not self.workspace.queue or not self.queue_steps_left:
            self.queue_running = False
            if self.workspace.queue and not self.queue_steps_left:
                self.collection_status.setText('本轮已结束；失败项已保留，点击“继续下载队列”重试')
                self.collection_bar.setValue(0)
                self.collection_bar.setFormat('有待重试项')
            elif not self.workspace.queue:
                self.collection_status.setText('下载队列已完成' if not self.queue_skipped else '队列已处理，已跳过不可用批次')
            if not self.queue_stopped:
                detail = f'完成 {self.queue_completed} 条 · 失败 {self.queue_failed} 条。{self.collection_status.text()}'
                self.task_notice(1, '智投下载队列结束', detail, attention=bool(self.workspace.queue))
            self.refresh_batch_list()
            self.task_finished.emit()
            return
        job = self.workspace.queue[0]
        try:
            self.batch = RecreationBatch.load(job['folder'])
        except (FileNotFoundError, ValueError):
            # An unavailable old batch must not block independent queued jobs.
            try:
                self.workspace.complete_download_job()
            except OSError:
                self.pause_download_round('失效批次无法从队列移出，保存失败；未启动后续下载')
                return
            self.queue_steps_left -= 1
            self.queue_skipped = getattr(self, 'queue_skipped', 0) + 1
            self.message.setText(f'已跳过 {self.queue_skipped} 个不可用批次；其他批次继续，原目录未删除。')
            QTimer.singleShot(0, self.start_next_download)
            return
        except OSError:
            self.pause_download_round('无法读取或写入批次记录，请检查磁盘和目录权限后继续')
            return
        self.load_batch_view()
        self.job_failed = False
        self.queue_remaining_ids = None
        self._start_browser_task('download', identities=job['identities'])
        if not self.collection_busy:
            self.pause_download_round(self.message.text() or '尚未连接智投，请检查登录')

    def pause_download_round(self, reason):
        self.queue_running = False
        self.message.setText(reason)
        self.collection_status.setText(reason)
        self.collection_bar.setRange(0, 1)
        self.collection_bar.setValue(0)
        self.collection_bar.setFormat('下载队列已暂停')
        if not self.queue_stopped:
            self.notify_download_pause(reason)
        self.refresh_batch_list()
        self.task_finished.emit()

    def notify_download_pause(self, reason):
        folder = self.workspace.queue[0]['folder'] if self.workspace.queue else ''
        self.task_notice(1, '智投下载待处理', reason, key=f'queue:{folder}:{reason}', attention=True)

    def stop_collection(self):
        self.queue_stopped = True
        super().stop_collection()

    def collection_failed(self, message):
        self.job_failed = True
        super().collection_failed(message)
        if self.queue_running and not self.queue_stopped:
            self.queue_pause_reason = self.message.text()
        elif not self.collection_stop.is_set():
            self.task_notice(1,'智投素材任务待处理',message,
                             key=f'collection:{getattr(self.batch,"folder","")}:{message}',attention=True)

    def collection_result(self, result):
        if super().collection_result(result) is False:
            self.job_failed = True
            if self.queue_running:
                self.queue_pause_reason = self.message.text()
            return
        self.job_failed = bool(result.get('stopped'))
        if self.queue_running:
            self.queue_completed += result.get('completed', 0)
            self.queue_failed += result.get('failed', 0)
            self.queue_remaining_ids = result.get('remaining_ids')
            self.queue_pause_reason = result.get('pause_reason', '')
        elif 'completed' in result and not self.pending_import:
            reason=result.get('pause_reason','')
            if reason:
                self.task_notice(1,'智投下载待处理',self.message.text(),
                                 key=f'download:{result.get("folder","")}:{reason}',attention=True)
            elif not result.get('stopped'):
                self.task_notice(1,'智投下载结束',self.message.text(),attention=bool(result.get('failed')))
        if self.pending_import and not result.get('stopped'):
            mode, folder, identities = self.pending_import
            self.complete_processing_import(mode, folder, identities)

    def collection_finished(self):
        self.pending_import = None
        was_queued = self.queue_running
        pause = ''
        if was_queued:
            pause = ('已手动暂停；已完成文件保留，继续时只下载剩余项' if self.queue_stopped else
                     self.queue_pause_reason or ('下载已暂停，队列保留' if self.job_failed else ''))
            try:
                if self.queue_remaining_ids is not None:
                    self.workspace.complete_download_job(self.queue_remaining_ids, defer=not pause)
                elif not pause:
                    self.workspace.complete_download_job()
            except OSError:
                pause = '队列记录保存失败，原任务已保留；请检查权限后继续'
            if pause:
                self.queue_running = False
            else:
                self.queue_steps_left -= 1
        super().collection_finished()
        self.refresh_batch_list()
        if was_queued and pause:
            self.collection_status.setText(pause)
            self.message.setText(pause)
            self.collection_bar.setValue(0)
            self.collection_bar.setFormat('下载队列已暂停')
            if not self.queue_stopped:
                self.notify_download_pause(pause)
        elif was_queued:
            QTimer.singleShot(0, self.start_next_download)
            self.refresh_batch_list()

    def open_processing_import(self, mode, *, from_download=False):
        if self.work_in_progress():
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('导入视频 · ' + ('改 MD5' if mode == 'md5' else '微创新'))
        dialog.resize(920, 560)
        box = QVBoxLayout(dialog)
        row = QHBoxLayout()
        selector = QComboBox()
        for folder in self.workspace.folders:
            try:
                b = RecreationBatch.load(folder, recover_interrupted=False)
            except (ValueError, OSError):
                continue
            selector.addItem(' / '.join(x['name'] or x['id'] for x in b.state['dramas']) + ' · ' + b.folder.name, folder)
        row.addWidget(selector, 1)
        row.addWidget(btn('从本地导入…', lambda: self.import_processing_local(mode, dialog, selector.currentData())))
        box.addLayout(row)
        videos = self._table(['勾选', '素材', '下载状态'])
        box.addLayout(self._selection_bar(videos))
        box.addWidget(videos, 1)
        items = []
        source_folder = str(self.batch.folder) if self.batch else None
        selected = {self.batch.state['sources'][i]['video_id'] for i in self.checked_rows(self.source_table)} if self.batch else set()
        def refresh():
            items.clear()
            videos.setRowCount(0)
            self._update_checked_count(videos)
            if not selector.currentData():
                return
            try:
                b = RecreationBatch.load(selector.currentData(), recover_interrupted=False)
                items.extend(b.state['sources'])
                videos.blockSignals(True)
                videos.setRowCount(len(items))
                for r, item in enumerate(items):
                    check = self._check_item(item['video_id'],
                        selected if from_download and selector.currentData() == source_folder else set())
                    videos.setItem(r, 0, check)
                    videos.setItem(r, 1, QTableWidgetItem(item['name']))
                    ready = item.get('path') and Path(item['path']).is_file()
                    videos.setItem(r, 2, QTableWidgetItem('本地可用' if ready else '未下载'))
                videos.blockSignals(False)
                self._update_checked_count(videos)
            except (OSError, ValueError) as exc:
                self.message.setText(str(exc))
        selector.currentIndexChanged.connect(refresh)
        if self.batch:
            selector.setCurrentIndex(selector.findData(str(self.batch.folder)))
        refresh()
        controls = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        controls.button(QDialogButtonBox.Ok).setText('导入勾选视频')
        controls.button(QDialogButtonBox.Cancel).setText('取消')
        local_only = controls.addButton('仅导入已下载的勾选项', QDialogButtonBox.ActionRole)
        local_only.setToolTip('只导入勾选项中本地存在的文件，不启动下载')
        local_only.clicked.connect(lambda: dialog.done(2))
        controls.accepted.connect(dialog.accept)
        controls.rejected.connect(dialog.reject)
        box.addWidget(controls)
        result = dialog.exec()
        if result in (QDialog.Accepted, 2):
            identities = [items[i]['video_id'] for i in self.checked_rows(videos)]
            if identities:
                self.request_processing_import(mode, selector.currentData(), identities, local_only=result == 2)
        self.selection_labels.pop(videos, None)
        dialog.deleteLater()

    def import_processing_local(self, mode, dialog, folder=None):
        if not folder and not self.batch:
            QMessageBox.information(self, '请选择批次', '请先创建或选择来源批次，以保留剧目信息。')
            return
        paths, _ = QFileDialog.getOpenFileNames(self, '导入本地视频', '', '视频 (*.mp4 *.mov *.mkv *.avi *.webm)')
        if paths:
            try:
                batch = RecreationBatch.load(folder or self.batch.folder, recover_interrupted=False)
                if len(batch.state['dramas']) != 1:
                    raise ValueError('历史多剧批次请先在下载页选择剧目并导入本地素材')
                batch.add_local_sources(paths, batch.state['dramas'][0])
                resolved = {str(Path(x).resolve()).casefold() for x in paths}
                ids = [x['video_id'] for x in batch.state['sources'] if x.get('path') and str(Path(x['path']).resolve()).casefold() in resolved]
                self.complete_processing_import(mode, str(batch.folder), ids)
                if self.batch and self.batch.folder == batch.folder:
                    self.batch = batch
                    self.refresh_sources()
                self.refresh_batch_list()
                dialog.reject()
            except (OSError, ValueError) as exc:
                self.message.setText(str(exc))

    def request_processing_import(self, mode, folder, identities, *, local_only=False):
        if not folder:
            self.message.setText('请选择来源批次')
            return
        try:
            batch = RecreationBatch.load(folder, recover_interrupted=False)
        except (OSError, ValueError):
            self.message.setText('来源批次不可用，请重新选择')
            return
        index = {item['video_id']: item for item in batch.state['sources']}
        if any(identity not in index for identity in identities):
            self.message.setText('来源素材记录缺失，请重新选择批次');return
        selected = [index[x] for x in identities]
        missing = [x for x in selected if not x.get('path') or not Path(x['path']).is_file()]
        if local_only:
            self.complete_processing_import(mode, folder, identities, local_only=True)
            return
        if not missing:
            self.complete_processing_import(mode, folder, identities)
            return
        if any(not x.get('source_material_id') for x in missing):
            self.message.setText('本地视频文件已移动或缺失，请从本地重新导入')
            return
        if QMessageBox.question(self, '下载后导入', f'{len(missing)} 条视频尚未下载。是否先下载，成功后加入处理列表？',
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.batch = batch
        self.load_batch_view()
        self.pending_import = (mode, folder, identities)
        self._start_browser_task('download', identities=[x['video_id'] for x in missing])
        if not self.collection_busy:
            self.pending_import = None

    def complete_processing_import(self, mode, folder, identities, *, local_only=False):
        try:
            batch = RecreationBatch.load(folder, recover_interrupted=False)
            index = {item['video_id']: item for item in batch.state['sources']}
            if any(identity not in index for identity in identities):
                raise ValueError('来源素材记录缺失，请重新选择批次')
            ready = [x for x in identities if (item := index[x]).get('path') and Path(item['path']).is_file()]
            if local_only and not ready:
                self.message.setText(f'没有可导入的本地文件；跳过 {len(identities)} 条')
                return
            self.workspace.add_inputs(mode, folder, ready)
            panel = self.md5 if mode == 'md5' else self.micro
            panel.refresh()
            self.tabs.setCurrentIndex(2 if mode == 'md5' else 3)
            self.message.setText(f'已导入 {len(ready)} 条；跳过 {len(identities)-len(ready)} 条未下载或已移走的文件'
                                 if local_only else
                                 f'已导入 {len(ready)} 条；未成功下载 {len(identities)-len(ready)} 条，未加入处理列表')
        except (OSError, ValueError, StopIteration) as exc:
            self.message.setText('导入未完成：' + str(exc))

    def process_selected(self):
        self.open_processing_import('md5', from_download=True)

    def processing_finished(self):
        self.refresh_outputs()
        self.task_finished.emit()

    def view_products(self, mode):
        self.output_filter.setCurrentIndex(self.output_filter.findData(mode))
        self.tabs.setCurrentIndex(4)

    def recover_products(self):
        if self.work_in_progress():
            self.message.setText('请先完成当前任务，再找回成品');return
        path,_=QFileDialog.getOpenFileName(self,'选择加工目录中的 manifest.json',str(self.batch.folder) if self.batch else '',
            '加工记录 (manifest.json)')
        if not path:return
        dialog=RecoveryDialog(path,self);self.recovery_dialog=dialog
        try:
            dialog.exec()
            if dialog.saved_batch is not None:
                batch=dialog.saved_batch;folder=str(batch.folder)
                if folder not in self.workspace.folders:self.workspace.folders.append(folder)
                index_error=False
                try:
                    self.workspace.path=self.preferences_path;self.workspace.save()
                except OSError:index_error=True
                if self.batch and self.batch.folder==batch.folder:self.batch=batch
                self.output_filter.setCurrentIndex(0);self.refresh_batch_list();self.refresh_outputs();self.tabs.setCurrentIndex(4)
                self.message.setText(f'已找回 {dialog.saved_count} 个成品；未触发上传。'+
                    ('索引保存失败，下次请从历史批次打开来源目录。' if index_error else ''))
        finally:
            self.recovery_dialog=None;dialog.deleteLater();self.task_finished.emit()

    def refresh_outputs(self):
        if not hasattr(self, 'workspace') or not hasattr(self, 'output_filter'):
            return super().refresh_outputs()
        self.catalog = []
        mode = self.output_filter.currentData()
        status_filter = self.output_state.currentData()
        search = self.output_search.text().strip().casefold()
        seen = set()
        for folder in self.workspace.folders:
            try:
                batch = RecreationBatch.load(folder, recover_interrupted=False)
            except (OSError, ValueError):
                continue
            states = {}
            rank = {'uploaded':0,'submitted':1,'review':2,'submission_review':3}
            platform_names = {}
            for entry in batch.state.get('uploads', []):
                status = entry.get('status','uploaded')
                for p in entry['files']:
                    if p not in states or rank.get(status,0)>=rank.get(states[p],0):
                        states[p] = status if status in rank else 'uploaded'
                names = entry.get('platform_names')
                if isinstance(names, dict):
                    platform_names.update(names)
            for item in batch.state['outputs']:
                if item['path'] in seen or (mode and item['mode'] != mode):
                    continue
                seen.add(item['path'])
                path = Path(item['path'])
                recorded = states.get(item['path'])
                state = (recorded if recorded in ('review','submission_review','submitted') else
                         'missing' if not path.is_file() else recorded or 'ready')
                try:
                    parts = path.relative_to(batch.folder / '加工成品').parts
                except ValueError:
                    parts = ()
                run = parts[0] if len(parts) == 4 else '未知'
                drama_id = item.get('upload_drama_info', {}).get('drama_platform_id', '')
                if (status_filter and state != status_filter) or (
                        search and search not in f"{item['drama']} {drama_id} {run}".casefold()):
                    continue
                self.catalog.append({**item, 'batch_folder': folder, 'uploaded_before': recorded in ('uploaded','submitted'),
                                     'upload_state': state, 'processing_run': run,
                                     'platform_upload_name': platform_names.get(item['path'], '')})
        checked = self._checked_identities(self.output_table)
        self.output_table.blockSignals(True)
        self.output_table.setRowCount(len(self.catalog))
        for row, item in enumerate(self.catalog):
            self.output_table.setItem(row, 0, self._check_item(item['path'], checked))
            status = {'review': '上传结果待核对', 'submission_review':'提交结果待核对',
                      'submitted':'已提交审核', 'missing': '文件缺失', 'uploaded': '已传文件 · 提交未确认',
                      'ready': '可上传'}[item['upload_state']]
            for col, value in enumerate((item['drama'], ('改 MD5' if item['mode'] == 'md5' else '微创新')
                    + ' · ' + item['processing_run'], Path(item['path']).name, status), 1):
                cell = QTableWidgetItem(value)
                info = item['platform_upload_name']
                cell.setToolTip(f'{value}\n平台文件名：{info}' if info and col in (3, 4) else value)
                self.output_table.setItem(row, col, cell)
        self.output_table.blockSignals(False)
        self._update_checked_count(self.output_table)

    def play_selected(self):
        rows = self.checked_rows(self.output_table)
        if rows:
            from src.desktop_widgets import local_open
            local_open(self.catalog[rows[0]]['path'])

    def prepare_upload(self):
        self.begin_upload()

    def refresh_director_hint(self):
        director = self.platform.upload_preferences.get('default_director', '')
        self.upload_director.setPlaceholderText(f'按剧目记忆；默认：{director}' if director else '留空时按剧目或默认值')

    def edit_default_director(self):
        value, accepted = QInputDialog.getText(self, '默认编导', '填入默认编导；保存空白可清除。',
            text=self.platform.upload_preferences.get('default_director', '') or self.upload_director.text())
        if not accepted:
            return
        try:
            self.platform.upload_preferences = remember_default_director(self.platform.preferences_path, value)
        except OSError:
            QMessageBox.warning(self, '未保存默认编导', '请检查配置目录是否可写。')
            return
        self.refresh_director_hint()

    def resolve_upload_director(self, drama, drama_id):
        prefs = self.platform.upload_preferences
        remembered = prefs['dramas'].get(drama, {}).get('ids', {}).get(drama_id, {})
        return self.upload_director.text().strip() or remembered.get('director') or prefs.get('default_director', '')

    def pause_upload(self):
        if self.upload_busy or self.auto_continue_group:
            self.upload_stop_event.set()
            self.cancel_auto_continuation()
            self.upload_status.setText('已请求暂停；已开始的上传或提交会等待平台结果'
                                       if self.upload_busy else '后续批次已暂停，可手动继续')

    def update_submit_hint(self):
        self.submit_hint.setText('本轮逐批上传并提交审核；确认回执后才会继续。'
                                 if self.submit_mode.currentData()=='auto' else
                                 '助手上传文件，你在智投确认提交。')

    def review_upload_records(self):
        if self.work_in_progress():
            return
        if self.upload_groups:
            self.upload_status.setText('请先结束本轮队列，再核对上传结果')
            return
        selected = [self.catalog[row] for row in self.checked_rows(self.output_table)]
        states = {item['upload_state'] for item in selected}
        if states not in ({'review'},{'submission_review'}):
            self.upload_status.setText('请勾选在智投逐条核实过的文件，上传和提交结果请分开核对')
            return
        submission = states == {'submission_review'}
        dialog = QMessageBox(self)
        dialog.setWindowTitle('记录核对结果')
        dialog.setText(f'已选 {len(selected)} 条。请只为已在智投逐条确认、且结果相同的文件记录状态。'
                       '此操作不会上传或提交。')
        uploaded = dialog.addButton('确认均已提交' if submission else '确认均已上传', QMessageBox.ActionRole)
        not_uploaded = dialog.addButton('确认均未提交，保留已上传' if submission else '确认均未上传，可重试',
                                        QMessageBox.ActionRole)
        cancel = dialog.addButton(QMessageBox.Cancel)
        dialog.setDefaultButton(cancel)
        dialog.exec()
        choice = dialog.clickedButton()
        if choice not in (uploaded, not_uploaded):
            return
        by_folder = defaultdict(set)
        for item in selected:
            by_folder[item['batch_folder']].add(item['path'])
        count, failed = 0, 0
        for folder, paths in by_folder.items():
            try:
                count += reconcile_upload(folder, paths, choice is uploaded, submission=submission)
            except (OSError, ValueError):
                failed += len(paths)
        self.refresh_outputs()
        self.upload_status.setText(f'已更新 {count} 条本地记录' + (f'；{failed} 条保存失败，仍待核对' if failed else ''))

    def refresh_upload_queue(self):
        group = self.upload_groups[0] if self.upload_groups else None
        self.upload_batch_files.clear()
        if group:
            self.upload_batch_summary.setText(
                f"第 {group.get('number', 1)} / {self.upload_total or len(self.upload_groups)} 批 · "
                f"{group['drama']} · {len(group['outputs'])} 条")
            for output in group['outputs']:
                item = QListWidgetItem(Path(output['path']).name)
                item.setToolTip(output['path'])
                self.upload_batch_files.addItem(item)
        else:
            self.upload_batch_summary.setText('尚无待传批次')
        ready = bool(group) and not self.upload_busy and not self.upload_needs_review
        self.auto_button.setEnabled(not group and not self.upload_busy)
        self.submit_mode.setEnabled(not group and not self.upload_busy)
        self.auto_button.setVisible(not group)
        self.next_upload_button.setVisible(bool(group))
        self.next_upload_button.setEnabled(ready)
        if group and group.get('auto_submit'):
            text = '上传并提交本轮' if group.get('number',1)==1 else '继续自动提交'
        else:
            text = '上传本批' if group and group.get('number',1)==1 else '确认上一批已处理，上传下一批'
        self.next_upload_button.setText(text)
        self.remove_upload_button.setEnabled(ready)
        self.cancel_upload_button.setEnabled(bool(group) and not self.upload_busy)

    def remove_queued_upload(self):
        if not self.upload_groups or self.upload_busy or self.upload_needs_review:
            return
        index = self.upload_batch_files.currentRow()
        if index < 0:
            self.upload_status.setText('请先在本批文件名单中选择一条')
            return
        group = self.upload_groups[0]
        del group['outputs'][index]
        if not group['outputs']:
            self.upload_groups.pop(0)
            if not self.upload_groups:
                self.submit_mode.setCurrentIndex(0)
        self.refresh_upload_queue()
        self.upload_status.setText('已移出待传队列，本地文件和上传记录保留')

    def cancel_upload_queue(self):
        if self.upload_busy or not self.upload_groups:
            return
        if QMessageBox.question(self, '结束本轮队列', '仅清空本轮待传计划，不删除文件、不改动平台表单。继续？',
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.upload_groups.clear()
        self.submit_mode.setCurrentIndex(0)
        self.cancel_auto_continuation()
        self.current_upload = None
        self.upload_needs_review = False
        self.refresh_upload_queue()
        self.upload_status.setText('队列已结束；待核对的记录仍保留')

    def begin_upload(self):
        if self.work_in_progress():
            return
        if self.upload_groups:
            self.message.setText('当前队列尚未结束，请继续上传或显式结束本轮队列')
            return
        selected = [self.catalog[r] for r in self.checked_rows(self.output_table)]
        if not selected:
            self.message.setText('请先勾选处理完成的成品')
            return
        if any(x.get('upload_state') in ('review','submission_review') for x in selected):
            self.message.setText('勾选项有平台结果待核对，请先在智投核实，不能直接重传')
            return
        if any(not Path(x['path']).is_file() for x in selected):
            self.message.setText('有成品文件缺失，请刷新后取消勾选缺失项；其他成品仍可上传')
            return
        uploaded = sum(bool(x.get('uploaded_before')) for x in selected)
        auto = self.submit_mode.currentData() == 'auto'
        if uploaded and auto:
            self.message.setText('自动提交仅接受尚未上传的成品，请取消勾选已上传或已提交的文件')
            return
        if uploaded and QMessageBox.question(self, '确认重复上传', f'{uploaded} 条成品已有成功上传记录。是否再次上传？',
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        groups = defaultdict(list)
        for item in selected:
            drama = item.get('upload_drama_info', {})
            if not drama.get('drama_platform_id') or not drama.get('drama_name'):
                self.message.setText('成品缺少剧目 ID 或剧名，请先确认来源批次')
                return
            groups[(item['batch_folder'], drama['drama_platform_id'], drama['drama_name'])].append(item)
        uploader = self.platform.uploader_initials.text().strip()
        directors = {key: self.resolve_upload_director(key[2], key[1]) for key in groups}
        if not uploader:
            self.message.setText('请填写右侧上传人缩写')
            return
        missing_director = next((key[2] for key, value in directors.items() if not value), None)
        if missing_director:
            self.message.setText(f'“{missing_director}”没有可用编导，请填写本轮编导或设置默认值')
            return
        if auto:
            scope = defaultdict(int)
            for key, items in groups.items():
                scope[(key[1],key[2],directors[key])] += len(items)
            rows = [f'{drama_id} · {name}｜{director}｜{count} 条'
                     for (drama_id,name,director),count in scope.items()]
            dialog = QMessageBox(QMessageBox.Question, '确认本轮自动提交',
                                 f'共 {len(selected)} 条、{len({k[1] for k in groups})} 部剧，可见范围为客户端二组。'
                                 '\n本轮将逐批上传并正式提交审核。仅在确认回执后继续。',
                                 QMessageBox.Yes | QMessageBox.No,self)
            dialog.setTextFormat(Qt.PlainText)
            dialog.setInformativeText('\n'.join(rows[:3]+(['… 查看全部剧目'] if len(rows)>3 else [])))
            dialog.button(QMessageBox.Yes).setText('启用本轮自动提交')
            dialog.button(QMessageBox.No).setText('取消')
            if len(rows)>3:
                dialog.setDetailedText('\n'.join(rows))
                for button in dialog.buttons():
                    if dialog.buttonRole(button)==QMessageBox.ActionRole:
                        button.setText('查看全部剧目')
            dialog.setDefaultButton(QMessageBox.No)
            if dialog.exec() != QMessageBox.Yes:
                return
        queue = []
        today = date.today()
        for key, items in groups.items():
            for start in range(0, len(items), 50):
                chunk = items[start:start+50]
                queue.append({'folder': key[0], 'drama_id': key[1], 'drama': key[2],
                    'outputs': chunk, 'upload_date':today, 'number':len(queue)+1,
                    'director':directors[key], 'uploader':uploader, 'auto_submit':auto})
        try:
            starts=reserve_recreation_upload_sequences(self.preferences_path.parent/'recreation-upload-sequences.sqlite3',
                ((recreation_upload_namespace(g['drama'],g['uploader'],today),len(g['outputs'])) for g in queue),
                self.historical_upload_names())
        except (OSError, ValueError, sqlite3.Error):
            self.message.setText('无法保存本机上传序号，未建立队列；请检查磁盘与配置目录权限')
            self.upload_status.setText(self.message.text())
            return
        for group,start in zip(queue,starts):
            group['sequence_start']=start
        self.upload_groups=queue
        self.upload_round_id=uuid4().hex
        self.upload_run_submitted=0
        self.upload_total = len(self.upload_groups)
        self.upload_status.setText('请核对本批名单后点击“上传并提交本轮”' if auto else
                                   '队列已建立，请核对本批名单后点击“上传本批”')
        self.refresh_upload_queue()

    def historical_upload_names(self):
        for folder in self.workspace.folders:
            try:
                batch=RecreationBatch.load(folder,recover_interrupted=False)
            except (FileNotFoundError, ValueError):
                continue
            for entry in batch.state.get('uploads',[]):
                names=entry.get('platform_names')
                if isinstance(names,dict):
                    yield from (name for name in names.values() if isinstance(name,str))

    def continue_upload(self):
        if self.work_in_progress() or not self.upload_groups or self.upload_needs_review:
            return
        self.cancel_auto_continuation()
        if self.platform.browser is None:
            self.open_login()
            self.message.setText('请先登录智投，完成后返回自动上传页继续')
            self.upload_status.setText(self.message.text())
            return
        target_id = self.platform.browser.page().devToolsId()
        if not target_id:
            self.message.setText('平台页面正在启动，请稍后继续')
            self.upload_status.setText(self.message.text())
            return
        port = self.platform.internal_browser_debug_port
        url = self.platform.address.text()
        self.upload_busy = True
        self.upload_attempt = None
        self.current_upload = None
        self.upload_stop_event.clear()
        self.upload_status.setText('正在检查平台表单，已有未提交内容时不会覆盖…')
        self.refresh_upload_queue()
        def check():
            ws = find_page_ws_url(url, port, target_id=target_id)
            state = evaluate_edge_page(ws, upload_script())
            if state.get('uploaded') or state.get('running') or state.get('unsaved') or state.get('selected'):
                raise RecreationPlatformError('平台表单存在上传或未提交内容，请先手动处理当前表单；不会覆盖')
            if state.get('error'):
                raise RecreationPlatformError(state['error'])
            return ws
        self.upload_task = Background(check, self)
        self.upload_task.result.connect(self.prepare_next_upload)
        self.upload_task.failed.connect(self.upload_failed)
        self.upload_task.finished.connect(self.task_finished.emit)
        self.upload_task.start()

    def prepare_next_upload(self, ws):
        if self.upload_stop_event.is_set():
            self.upload_failed('自动上传已停止，未选择或上传新文件')
            return
        self.upload_ws = ws
        self.upload_status.setText('正在生成文件名并准备本批平台表单…')
        group = self.upload_groups[0]
        # Files or batch records can disappear while the platform check runs.
        try:
            batch = RecreationBatch.load(group['folder'], recover_interrupted=False)
            if any(not Path(x['path']).is_file() for x in group['outputs']):
                raise ValueError('成品文件已移走或删除')
        except (OSError, ValueError):
            self.upload_failed('本批文件或记录已失效，未启动上传；请移出失效项或结束队列后重新选择')
            return
        paths = {x['path'] for x in group['outputs']}
        if any(entry.get('status') in ('review','submission_review') and paths.intersection(entry['files'])
               for entry in batch.state.get('uploads', [])):
            self.upload_needs_review = True
            self.upload_failed('本批含待核对文件，未启动上传')
            return
        self.current_upload = group
        records = {}
        try:
            rows = local_files_to_rows(item['path'] for item in group['outputs'])
            if len(rows) != len(group['outputs']):
                raise ValueError('本批有重复的文件路径')
        except (OSError, ValueError):
            self.upload_failed('当批文件已移动或存在重复路径，未启动上传')
            return
        for row, item in zip(rows, group['outputs']):
            row.update(processing_mode=item['mode'], upload_drama_info=item['upload_drama_info'])
            row['source']['剧名'] = item['drama']
            records[row['video_id']] = {'video_path': item['path'], 'metadata': item['metadata'],
                'download': '已下载', 'status': 'review_required', 'reason': '仅下载，未调用模型', 'processing_mode': item['mode']}
        self.platform.set_materials(rows, records, {}, set(records), Path(group['folder']))
        self.platform.drama_name.setText(group['drama'])
        self.platform.drama_id.setCurrentText(group['drama_id'])
        self.platform.director.setText(group['director'])
        self.platform.uploader_initials.setText(group['uploader'])
        self.platform.upload_sequence_start = group.get('sequence_start', 1)
        self.platform.upload_sequence_date = group.get('upload_date')
        self.auto_upload_pending = True
        if not self.platform.prepare_upload():
            self.upload_failed(self.platform.preview.text())

    def staging_for_upload_ready(self):
        if self.upload_stop_event.is_set() and self.upload_busy:
            self.upload_failed('自动上传已停止，暂存文件保留，未上传')
            return
        if self.auto_upload_pending:
            self.upload_status.setText('正在填写平台表单并选取本批文件…')
            self.platform.fill_platform_form()

    def files_for_upload_ready(self, result):
        if self.upload_stop_event.is_set() and self.upload_busy:
            self.upload_failed('自动上传已停止，页面选中文件保留，未点击上传')
            return
        if not self.auto_upload_pending:
            return
        self.auto_upload_pending = False
        group = self.current_upload
        batches = self.platform.upload_batches
        if group is None or len(batches) != 1:
            self.upload_failed('上传暂存与当前批次不一致，未启动上传')
            return
        batch = batches[0]
        names = [x['upload_name'] for x in batch['items']]
        expected = [str(Path(x['path']).resolve()) for x in group['outputs']]
        staged = [str(Path(x['original_path']).resolve()) for x in batch['items']]
        if not names or staged != expected or len(set(names)) != len(names):
            self.upload_failed('暂存文件与本批名单不一致，未启动上传')
            return
        attempt = uuid4().hex
        try:
            record_upload(group, attempt, 'review', names=names)
        except (OSError, ValueError):
            self.upload_failed('无法保存本批上传记录，未启动上传')
            return
        self.upload_attempt = attempt
        self.upload_status.setText('文件已选取，正在启动上传…')
        ws = self.upload_ws
        task = None
        def transfer():
            try:
                result = upload_files(ws, names, group['drama_id'],
                    should_stop=self.upload_stop_event.is_set, progress=task.progress.emit)
            except UploadNotStarted as exc:
                return {'stopped': True, 'message': str(exc)}
            if result.get('stopped') or not group.get('auto_submit'):
                return result
            if self.upload_stop_event.is_set():
                return {**result,'submit_note':'已暂停自动提交，请到智投人工处理当前表单。'}
            if result['uploaded'] != len(names) or result.get('failed'):
                raise RuntimeError('文件未全部上传，未提交')
            # Persist uncertainty before the first action that can submit.
            try:
                record_upload(group, attempt, 'submission_review', result['uploaded'])
            except (OSError, ValueError) as exc:
                raise RecreationPlatformError('无法保存提交前的本地记录，未提交审核') from exc
            task.progress.emit({'phase':'submitting'})
            try:
                receipt = submit_uploaded_batch(ws,attempt,names,group['drama_id'],group['director'],
                                                 should_stop=self.upload_stop_event.is_set)
            except SubmitNotStarted as exc:
                return {**result,'submit_note':f'{exc}。请到智投人工处理当前表单。'}
            if receipt is None:
                return {**result,'submit_note':'已暂停自动提交，请到智投人工处理当前表单。'}
            try:
                record_upload(group, attempt, 'submitted', result['uploaded'], receipt=receipt)
            except (OSError, ValueError) as exc:
                raise RecreationPlatformError('智投已返回审核回执，但本地未能保存；请在平台核对，不会续传') from exc
            try:
                closed = close_submission_receipt(ws,attempt)
            except Exception:
                # A confirmed receipt is already on disk. Losing the connection
                # while closing must not turn that confirmation into a retry.
                closed = False
            return {**result,'submitted':True,'form_closed':closed}
        task = Background(transfer, self)
        self.upload_task = task
        def progress(state):
            note = ('正在提交审核并等待智投回执…' if state.get('phase')=='submitting' else
                    f"成功 {state['uploaded']} / {len(names)} · 失败 {state['failed']}")
            self.message.setText(note)
            self.upload_status.setText(note)
        task.progress.connect(progress)
        task.result.connect(self.upload_completed)
        task.failed.connect(self.upload_failed)
        task.finished.connect(self.upload_transfer_finished)
        task.start()

    def upload_transfer_finished(self):
        self.task_finished.emit()
        if self.auto_continue_group:
            self.upload_continue_timer.start(0)

    def cancel_auto_continuation(self):
        self.auto_continue_group=None
        self.upload_continue_timer.stop()

    def resume_auto_upload(self):
        ticket=self.auto_continue_group
        if (not ticket or not self.upload_groups or self.upload_groups[0] is not ticket
                or self.upload_stop_event.is_set() or self.upload_needs_review):
            self.cancel_auto_continuation()
            return
        if self.work_in_progress():
            self.upload_status.setText(f"第 {ticket['number']} 批等待其他任务完成，空闲后自动继续")
            self.upload_continue_timer.start(500)
            return
        self.cancel_auto_continuation()
        self.continue_upload()

    def upload_completed(self, result):
        group, attempt = self.current_upload, self.upload_attempt
        if not group or not self.upload_groups or self.upload_groups[0] is not group:
            return
        self.upload_attempt = None
        self.upload_busy = False
        self.current_upload = None
        try:
            if result.get('stopped'):
                if attempt:
                    record_upload(group, attempt, None)
                self.message.setText(result['message'])
            elif result.get('submitted'):
                self.upload_groups.pop(0)
                self.upload_run_submitted+=result['uploaded']
                self.message.setText(f"第 {group.get('number',1)} 批已提交审核 · {result['uploaded']} 条")
                if not result.get('form_closed'):
                    self.message.setText(self.message.text()+'；请关闭智投回执后再继续')
                    self.task_notice(4,'需关闭智投回执',self.message.text(),attention=True)
                elif self.upload_groups and not self.upload_stop_event.is_set():
                    self.auto_continue_group = self.upload_groups[0]
                elif self.upload_groups:
                    self.message.setText(self.message.text()+'；后续批次已暂停')
                else:
                    self.task_notice(4,'自动提交审核本轮结束',f'本轮已提交审核 {self.upload_run_submitted} 条')
            else:
                record_upload(group, attempt, 'uploaded', result['uploaded'])
                self.upload_groups.pop(0)
                self.message.setText(f"第 {group.get('number', 1)} 批上传 {result['uploaded']} 条成功，未提交。"+
                                     result.get('submit_note','请到智投人工处理当前表单。'))
                self.task_notice(4,'文件已传，待提交',self.message.text(),attention=True)
        except (OSError, ValueError):
            self.upload_needs_review = True
            self.message.setText('上传结果未能保存，队列已暂停；请先在智投核对当前表单。')
            self.task_notice(4,'上传结果待核对',self.message.text(),attention=True)
        self.refresh_outputs()
        if not self.upload_groups:
            self.submit_mode.setCurrentIndex(0)
        self.refresh_upload_queue()
        self.upload_status.setText(self.message.text())
        self.task_finished.emit()

    def upload_failed(self, message):
        if not self.upload_busy:
            return
        if self.upload_attempt:
            self.upload_needs_review = True
            self.upload_attempt = None
            message += '；本批结果待核对，不会自动重传'
            self.refresh_outputs()
        self.current_upload = None
        self.platform.materials_generation += 1
        self.upload_busy = self.auto_upload_pending = False
        self.refresh_upload_queue()
        self.message.setText(message)
        self.upload_status.setText(message)
        if not self.upload_stop_event.is_set() or self.upload_needs_review:
            self.task_notice(4,'上传或提交待处理',message,key=f'upload:{self.upload_round_id}:{message}',attention=True)
        self.task_finished.emit()

    def request_stop_all(self):
        self.schedule.stop_on_close()
        self.cancel_auto_continuation()
        if self.recovery_dialog is not None:self.recovery_dialog.reject()
        self.stop_collection()
        for panel in (self.md5, self.micro):
            if panel.busy:
                panel.stop()
        self.upload_stop_event.set()
