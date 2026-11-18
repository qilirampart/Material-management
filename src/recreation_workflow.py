"""Six-stage recreation UI. Reuses the established batch and platform engines."""
import threading
from collections import defaultdict
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QListWidgetItem, QDialog, QPlainTextEdit, QDialogButtonBox, QFileDialog,
    QComboBox, QTableWidgetItem, QMessageBox, QFormLayout)
from src.recreation_page import RecreationPage
from src.recreation_workspace import RecreationWorkspace
from src.recreation_cleanup_page import CleanupPage
from src.recreation_processing import ProcessingWorkbench
from src.recreation import RecreationBatch
from src.recovery_dialog import RecoveryDialog
from src.material_name_filter import name_is_excluded
from src.recreation_platform import RecreationPlatformError
from src.recreation_upload import upload_files, upload_script
from src.ui_design import card, label, btn, Background
from src.task_input import local_files_to_rows
from src.edge_cdp import find_page_ws_url, evaluate_edge_page


class RecreationWorkflowPage(RecreationPage):
    def __init__(self, config, *, restore=True):
        config = dict(config)
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
        self.upload_task, self.upload_busy = None, False
        self.upload_stop_event = threading.Event()
        self.upload_groups, self.catalog = [], []
        self.recovery_dialog=None
        self.auto_upload_pending = False
        self.current_upload = None
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
        collect.layout().insertWidget(0, self.batch_heading)
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
        box.addLayout(self._selection_bar_reparent(self.output_table))
        box.addWidget(self.output_table, 1)
        self.output_table.setHorizontalHeaderLabels(['勾选', '剧目', '处理来源', '成品', '文件状态'])
        box.addWidget(label('按剧目分组，每批最多 50 条。每批上传后停在提交前，人工处理当前表单后继续下一批。'))
        controls = QHBoxLayout()
        controls.addWidget(btn('播放勾选成品', self.play_selected))
        controls.addWidget(btn('刷新成品列表', self.refresh_outputs))
        self.recover_button=btn('找回加工成品…',self.recover_products)
        controls.addWidget(self.recover_button)
        controls.addStretch()
        box.addLayout(controls)
        upload_box.addWidget(products, 1)
        self.platform.preparation_card.hide()
        settings, prep = card('上传设置')
        settings.setFixedWidth(340)
        upload_box.addWidget(settings)
        prep.addWidget(label('共用第 1 步登录 · 客户端二组'))
        fields = QFormLayout()
        fields.addRow('编导', self.platform.director)
        fields.addRow('上传人缩写', self.platform.uploader_initials)
        fields.addRow('建议短剧', label('按成品所属剧目自动填写'))
        fields.addRow('可见范围', label('客户端二组'))
        prep.addLayout(fields)
        prep.addWidget(label('只上传勾选成品，不保存草稿或最终提交。'))
        prep.addStretch()
        self.upload_status = label('待开始 · 没有正在上传的文件')
        prep.addWidget(self.upload_status)
        # Replace the manual-only action with explicit auto-upload controls; the
        # original component remains unchanged for the original workflow.
        self.auto_button = btn('开始上传勾选成品', self.begin_upload, True)
        self.next_upload_button = btn('继续下一批（当前表单已处理）', self.continue_upload)
        self.next_upload_button.setEnabled(False)
        prep.addWidget(self.auto_button)
        prep.addWidget(self.next_upload_button)
        prep.addWidget(btn('停止后续批次（等待当前上传）', self.upload_stop_event.set))
        prep.addWidget(btn('查看智投页面', self.open_login))
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
        self.batch_list.currentRowChanged.connect(self.select_batch)
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
        return tasks

    def own_work_in_progress(self):
        return (super().own_work_in_progress() or getattr(self, 'upload_busy', False)
                or getattr(self, 'cleanup_busy', False)
                or getattr(getattr(self,'recovery_dialog',None),'busy',False)
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
        self.output_root = Path(config['output_root'])
        self.workspace.root = self.output_root
        self.platform.config = dict(config)
        self.platform.address.setText(config.get('platform_url') or 'https://market.wuread.cn/market-admin/')
        self.file_cleanup.refresh()

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
                names = ' / '.join(x['name'] or x['id'] for x in batch.state['dramas'])
                available = sum(bool(x.get('path')) and Path(x['path']).is_file() for x in batch.state['sources'])
                text = f'批次 {i+1:02d}\n{names[:12]}\n{names[12:24]}' if len(names) > 12 else f'批次 {i+1:02d}\n{names}'
                text += f"\n共 {len(batch.state['sources'])} 条 · 本地 {available} 条"
            except (OSError, ValueError):
                text = Path(folder).name + '\n批次不可用，请检查目录'
            item = QListWidgetItem(text)
            item.setToolTip(folder)
            item.setData(Qt.UserRole, folder)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if folder in checked else Qt.Unchecked)
            self.batch_list.addItem(item)
            if folder == current:
                active = i
        self.batch_list.setCurrentRow(active)
        self.batch_list.blockSignals(False)
        self.queue_summary.setText(f'下载队列 {len(self.workspace.queue)} 个批次' + (' · 已暂停' if not self.queue_running else ' · 运行中'))
        if getattr(self, 'queue_skipped', 0):
            self.queue_summary.setText(self.queue_summary.text() + f' · 已跳过 {self.queue_skipped} 个失效批次')

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
            batches = self.workspace.create(self.drama_input.toPlainText(),exclude_name=self.exclude_name.text())
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
            batches = self.workspace.import_files(paths,exclude_name=self.exclude_name.text())
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
        try:
            for i in range(self.batch_list.count()):
                item = self.batch_list.item(i)
                if item.checkState() != Qt.Checked:
                    continue
                batch = RecreationBatch.load(item.data(Qt.UserRole))
                ids = [x['video_id'] for x in batch.state['sources'] if x.get('source_material_id')
                    and not name_is_excluded(x['name'],batch.state.get('exclude_name',''))]
                if not ids:
                    raise ValueError('有批次尚未获取素材，请先获取再加入下载队列')
                self.workspace.enqueue(batch.folder, ids)
            self.refresh_batch_list()
            self.resume_download_queue()
        except (OSError, ValueError) as exc:
            self.message.setText(str(exc))

    def resume_download_queue(self):
        if self.work_in_progress() or not self.workspace.queue:
            return
        self.queue_running, self.queue_stopped = True, False
        self.queue_skipped = 0
        self.start_next_download()

    def manage_batches(self):
        if self.work_in_progress():
            self.message.setText('请先完成或停止当前任务，再清理批次')
            return
        folders = [self.batch_list.item(i).data(Qt.UserRole) for i in range(self.batch_list.count())
                   if self.batch_list.item(i).checkState() == Qt.Checked]
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
        if self.work_in_progress():
            self.message.setText('当前任务尚未结束，未执行清理')
            return
        from src.recreation_cleanup import execute_cleanup
        self.cleanup_busy = True
        self.cleanup_button.setEnabled(False)
        self.file_cleanup.set_busy(True)
        self.message.setText('正在清理勾选批次，请等待文件和记录同步完成…')
        def execute():
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
            self.next_upload_button.setEnabled(False)
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
        if self.queue_stopped or not self.workspace.queue:
            self.queue_running = False
            self.refresh_batch_list()
            self.task_finished.emit()
            return
        job = self.workspace.queue[0]
        try:
            self.batch = RecreationBatch.load(job['folder'])
        except (OSError, ValueError):
            # An unavailable old batch must not block independent queued jobs.
            self.workspace.queue.pop(0)
            try:
                self.workspace.save()
            except OSError:
                self.workspace.queue.insert(0, job)
                self.queue_running = False
                self.message.setText('失效批次无法从队列移出，保存失败；未启动后续下载')
                return
            self.queue_skipped = getattr(self, 'queue_skipped', 0) + 1
            self.message.setText(f'已跳过 {self.queue_skipped} 个不可用批次；其他批次继续，原目录未删除。')
            QTimer.singleShot(0, self.start_next_download)
            return
        self.load_batch_view()
        self.job_failed = False
        self._start_browser_task('download', identities=job['identities'])
        if not self.collection_busy:
            self.queue_running = False

    def stop_collection(self):
        self.queue_stopped = True
        super().stop_collection()

    def collection_failed(self, message):
        self.job_failed = True
        super().collection_failed(message)

    def collection_result(self, result):
        if super().collection_result(result) is False:
            self.job_failed = True
            return
        self.job_failed = bool(result.get('stopped'))
        if self.pending_import and not result.get('stopped'):
            mode, folder, identities = self.pending_import
            self.complete_processing_import(mode, folder, identities)

    def collection_finished(self):
        self.pending_import = None
        if self.queue_running and not self.job_failed and not self.queue_stopped:
            self.workspace.queue.pop(0)
            try:
                self.workspace.save()
            except OSError:
                self.queue_stopped = True
                self.message.setText('队列记录保存失败，已停止；已完成视频保留')
        super().collection_finished()
        self.refresh_batch_list()
        if self.queue_running and not self.job_failed and not self.queue_stopped:
            QTimer.singleShot(0, self.start_next_download)
        else:
            self.queue_running = False
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
        selected = {self.batch.state['sources'][i]['video_id'] for i in self.checked_rows(self.source_table)} if self.batch else set()
        def refresh():
            items.clear()
            if not selector.currentData():
                return
            try:
                b = RecreationBatch.load(selector.currentData(), recover_interrupted=False)
                items.extend(b.state['sources'])
                videos.blockSignals(True)
                videos.setRowCount(len(items))
                for r, item in enumerate(items):
                    check = self._check_item(item['video_id'], selected if from_download else set())
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
        controls.accepted.connect(dialog.accept)
        controls.rejected.connect(dialog.reject)
        box.addWidget(controls)
        if dialog.exec() == QDialog.Accepted:
            identities = [items[i]['video_id'] for i in self.checked_rows(videos)]
            if identities:
                self.request_processing_import(mode, selector.currentData(), identities)
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

    def request_processing_import(self, mode, folder, identities):
        batch = RecreationBatch.load(folder, recover_interrupted=False)
        index = {item['video_id']: item for item in batch.state['sources']}
        if any(identity not in index for identity in identities):
            self.message.setText('来源素材记录缺失，请重新选择批次');return
        selected = [index[x] for x in identities]
        missing = [x for x in selected if not x.get('path') or not Path(x['path']).is_file()]
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

    def complete_processing_import(self, mode, folder, identities):
        try:
            batch = RecreationBatch.load(folder, recover_interrupted=False)
            index = {item['video_id']: item for item in batch.state['sources']}
            if any(identity not in index for identity in identities):
                raise ValueError('来源素材记录缺失，请重新选择批次')
            ready = [x for x in identities if (item := index[x]).get('path') and Path(item['path']).is_file()]
            self.workspace.add_inputs(mode, folder, ready)
            panel = self.md5 if mode == 'md5' else self.micro
            panel.refresh()
            self.tabs.setCurrentIndex(2 if mode == 'md5' else 3)
            self.message.setText(f'已导入 {len(ready)} 条；未成功下载 {len(identities)-len(ready)} 条，未加入处理列表')
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
        seen = set()
        for folder in self.workspace.folders:
            try:
                batch = RecreationBatch.load(folder, recover_interrupted=False)
            except (OSError, ValueError):
                continue
            for item in batch.state['outputs']:
                if item['path'] in seen or (mode and item['mode'] != mode):
                    continue
                seen.add(item['path'])
                uploaded = any(item['path'] in entry.get('files', []) for entry in batch.state.get('uploads', []))
                self.catalog.append({**item, 'batch_folder': folder, 'uploaded_before': uploaded})
        checked = self._checked_identities(self.output_table)
        self.output_table.blockSignals(True)
        self.output_table.setRowCount(len(self.catalog))
        for row, item in enumerate(self.catalog):
            self.output_table.setItem(row, 0, self._check_item(item['path'], checked))
            for col, value in enumerate((item['drama'], '改 MD5' if item['mode'] == 'md5' else '微创新',
                    Path(item['path']).name, ('已上传（提交由平台确认）' if item['uploaded_before'] else '可上传')
                    if Path(item['path']).is_file() else '文件缺失'), 1):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
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

    def begin_upload(self):
        if self.work_in_progress():
            return
        selected = [self.catalog[r] for r in self.checked_rows(self.output_table)]
        if not selected:
            self.message.setText('请先勾选处理完成的成品')
            return
        if any(not Path(x['path']).is_file() for x in selected):
            self.message.setText('有成品文件缺失，请刷新后取消勾选缺失项；其他成品仍可上传')
            return
        uploaded = sum(bool(x.get('uploaded_before')) for x in selected)
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
        self.upload_groups = []
        sequences = defaultdict(int)
        for key, items in groups.items():
            for start in range(0, len(items), 50):
                chunk = items[start:start+50]
                self.upload_groups.append({'folder': key[0], 'drama_id': key[1], 'drama': key[2],
                    'outputs': chunk, 'sequence_start': sequences[key[1]] + 1})
                sequences[key[1]] += len(chunk)
        if not self.platform.director.text().strip() or not self.platform.uploader_initials.text().strip():
            self.message.setText('请填写右侧编导与上传人缩写')
            return
        self.continue_upload()

    def continue_upload(self):
        if self.work_in_progress() or not self.upload_groups:
            return
        if self.platform.browser is None:
            self.open_login()
            self.message.setText('请先登录智投，完成后返回自动上传页继续')
            return
        target_id = self.platform.browser.page().devToolsId()
        if not target_id:
            self.message.setText('平台页面正在启动，请稍后继续')
            return
        port = self.platform.internal_browser_debug_port
        url = self.platform.address.text()
        self.upload_busy = True
        self.upload_stop_event.clear()
        self.upload_operator = (self.platform.director.text().strip(), self.platform.uploader_initials.text().strip())
        self.upload_status.setText('正在检查平台表单，已有未提交内容时不会覆盖…')
        self.auto_button.setEnabled(False)
        self.next_upload_button.setEnabled(False)
        def check():
            ws = find_page_ws_url(url, port, target_id=target_id)
            state = evaluate_edge_page(ws, upload_script())
            if state.get('uploaded') or state.get('running') or state.get('unsaved'):
                raise RecreationPlatformError('平台表单存在上传或未提交内容，请先手动处理当前表单；不会覆盖')
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
            RecreationBatch.load(group['folder'], recover_interrupted=False)
            if any(not Path(x['path']).is_file() for x in group['outputs']):
                raise ValueError('成品文件已移走或删除')
        except (OSError, ValueError):
            self.upload_failed('本批文件或记录已失效，未启动上传；请刷新后重新勾选可用成品')
            return
        self.current_upload = group
        rows, records = [], {}
        for item in group['outputs']:
            row = local_files_to_rows([item['path']])[0]
            row.update(processing_mode=item['mode'], upload_drama_info=item['upload_drama_info'])
            row['source']['剧名'] = item['drama']
            rows.append(row)
            records[row['video_id']] = {'video_path': item['path'], 'metadata': item['metadata'],
                'download': '已下载', 'status': 'review_required', 'reason': '仅下载，未调用模型', 'processing_mode': item['mode']}
        self.platform.set_materials(rows, records, {}, set(records), Path(group['folder']))
        self.platform.drama_name.setText(group['drama'])
        self.platform.drama_id.setCurrentText(group['drama_id'])
        self.platform.director.setText(self.upload_operator[0])
        self.platform.uploader_initials.setText(self.upload_operator[1])
        self.platform.upload_sequence_start = group.get('sequence_start', 1)
        self.auto_upload_pending = True
        if not self.platform.prepare_upload():
            self.upload_failed(self.platform.preview.text())

    def staging_for_upload_ready(self):
        if self.upload_stop_event.is_set() and self.upload_busy:
            self.upload_failed('自动上传已停止，暂存文件保留，未上传')
            return
        if self.auto_upload_pending:
            self.platform.fill_platform_form()

    def files_for_upload_ready(self, result):
        if self.upload_stop_event.is_set() and self.upload_busy:
            self.upload_failed('自动上传已停止，页面选中文件保留，未点击上传')
            return
        if not self.auto_upload_pending:
            return
        self.auto_upload_pending = False
        batch = self.platform.upload_batches[0]
        names = [x['upload_name'] for x in batch['items']]
        self.upload_stop_event.clear()
        task = None
        def transfer():
            return upload_files(self.upload_ws, names, self.current_upload['drama_id'],
                should_stop=self.upload_stop_event.is_set, progress=task.progress.emit)
        task = Background(transfer, self)
        self.upload_task = task
        task.progress.connect(lambda state: self.message.setText(
            f"平台上传：成功 {state['uploaded']} / {len(names)} · 失败 {state['failed']}"))
        task.progress.connect(lambda state: self.upload_status.setText(f"成功 {state['uploaded']} / {len(names)} · 失败 {state['failed']}"))
        task.result.connect(self.upload_completed)
        task.failed.connect(self.upload_failed)
        task.finished.connect(self.task_finished.emit)
        task.start()

    def upload_completed(self, result):
        self.upload_busy = False
        self.auto_button.setEnabled(True)
        if not result.get('stopped'):
            self.upload_groups.pop(0)
            self.message.setText(f"本批 {result['uploaded']} 条上传成功，未提交。请到登录页人工处理当前表单后继续下一批。")
            try:
                entry = {
                    'drama_id': self.current_upload['drama_id'], 'files': [x['path'] for x in self.current_upload['outputs']],
                    'uploaded': result['uploaded'], 'submitted': False}
                batch = RecreationBatch.load(self.current_upload['folder'], recover_interrupted=False)
                batch.state.setdefault('uploads', []).append(entry)
                batch.save()
                self.refresh_outputs()
            except (OSError, ValueError):
                self.message.setText(self.message.text() + ' 上传记录保存失败，请保留当前表单。')
        else:
            self.message.setText(result['message'])
        self.next_upload_button.setEnabled(bool(self.upload_groups))
        self.upload_status.setText(self.message.text())
        self.task_finished.emit()

    def upload_failed(self, message):
        if not self.upload_busy:
            return
        self.upload_busy = self.auto_upload_pending = False
        self.auto_button.setEnabled(True)
        self.next_upload_button.setEnabled(bool(self.upload_groups))
        self.message.setText(message)
        self.upload_status.setText(message)
        self.task_finished.emit()

    def request_stop_all(self):
        if self.recovery_dialog is not None:self.recovery_dialog.reject()
        self.stop_collection()
        for panel in (self.md5, self.micro):
            if panel.busy:
                panel.stop()
        self.upload_stop_event.set()
