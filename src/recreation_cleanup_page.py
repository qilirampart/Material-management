"""Lazy file browsing and explicit preview/confirm cleanup, integrated with workflow."""
from pathlib import Path
from PySide6.QtCore import Qt, QDir, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTreeView,
    QAbstractItemView, QPlainTextEdit, QMessageBox, QSplitter, QFileSystemModel, QStackedWidget)
from src.ui_design import card, label, btn, Background
from src.recreation_cleanup import plan_selection


class CleanupFileModel(QFileSystemModel):
    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole and 0 <= section < 4:
            return ('文件 / 文件夹', '大小', '类型', '修改时间')[section]
        return super().headerData(section, orientation, role)


class CleanupPage(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner, self.plan = owner, None
        box = QVBoxLayout(self); box.setContentsMargins(0, 0, 0, 0)
        surface, body = card('文件清理')
        box.addWidget(surface)
        self.root_label = label('')
        self.root_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.addWidget(self.root_label)
        tools = QHBoxLayout()
        self.refresh_button = btn('刷新目录', self.refresh)
        tools.addWidget(self.refresh_button)
        tools.addWidget(btn('打开素材目录', self.open_root))
        tools.addStretch()
        tools.addWidget(btn('全选当前层', lambda: self.tree.selectAll()))
        tools.addWidget(btn('清除选择', lambda: self.tree.clearSelection()))
        body.addLayout(tools)
        self.guide = label(
            '1. 选择范围：选中文件夹或具体的视频文件，支持 Ctrl / Shift 多选。\n'
            '2. 预览清单：点击“预览待删除文件”，核对文件名、数量和大小。\n'
            '3. 确认删除：预览完成且有可删除文件后，右侧删除按钮才会启用；核对后点击并确认。', 'summary')
        body.addWidget(self.guide)
        split = QSplitter(Qt.Vertical)
        self.tree = QTreeView()
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setAlternatingRowColors(True)
        self.tree.setMinimumHeight(190)
        self.tree.setStyleSheet('QTreeView {background:white; border:1px solid #DCE5E7; '
            'alternate-background-color:#FAFCFC; selection-background-color:#E6F3F0; '
            'selection-color:#143F3B;} QTreeView::item { min-height:28px; }')
        self.file_browser = QStackedWidget()
        self.file_browser.addWidget(self.tree)
        self.missing_directory = label('素材保存目录不存在\n点击“打开素材目录”创建并打开，或在设置中选择已有素材目录。')
        self.missing_directory.setAlignment(Qt.AlignCenter)
        self.file_browser.addWidget(self.missing_directory)
        split.addWidget(self.file_browser)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText('选择范围后，点击“预览待删除文件”，这里会显示实际要删除的文件。')
        self.preview.setMinimumHeight(100)
        split.addWidget(self.preview)
        split.setStretchFactor(0, 3); split.setStretchFactor(1, 1)
        body.addWidget(split, 1)
        self.safety_notice = label('仅清理可确认归属的 MP4 视频及配套封面。文档、配置、批次记录、外部原文件及无法确认归属的文件不删除；文件夹保留。历史批次无需加入当前列表。')
        body.addWidget(self.safety_notice)
        self.status = label('请选择要清理的文件或文件夹')
        body.addWidget(self.status)
        actions = QHBoxLayout()
        self.preview_button = btn('预览待删除文件', self.prepare)
        self.delete_button = btn('确认删除清单中的文件…', self.confirm, True)
        self.delete_button.setEnabled(False)
        actions.addWidget(self.preview_button)
        actions.addStretch()
        actions.addWidget(self.delete_button)
        body.addLayout(actions)
        self.model = None
        self.refresh()

    def open_root(self):
        self.root = Path(self.owner.output_root).resolve()
        if not self.root.is_dir():
            if QMessageBox.question(self, '素材目录不存在',
                    f'当前素材保存目录不存在：\n{self.root}\n\n是否创建并打开？\n'
                    '如果素材保存在其他位置，请在设置中修改素材保存目录。',
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
            try:
                self.root.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                QMessageBox.warning(self, '无法创建素材目录', f'{self.root}\n\n{exc}')
                return
            self.refresh()
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.root))):
            QMessageBox.warning(self, '无法打开素材目录', f'系统未能打开以下目录，可复制路径手动打开：\n{self.root}')

    def invalidate(self):
        self.plan = None
        self.preview.clear()
        self.delete_button.setEnabled(False)
        selection = self.tree.selectionModel()
        count = len(selection.selectedRows()) if selection else 0
        self.status.setText(f'已选 {count} 项 · 下一步：点击“预览待删除文件”')

    def refresh(self):
        self.root = Path(self.owner.output_root).resolve()
        self.root_label.setText('素材保存目录：' + str(self.root))
        old = self.model
        self.model = CleanupFileModel(self)
        self.model.setReadOnly(True)
        self.model.setOption(QFileSystemModel.DontWatchForChanges, True)
        self.model.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot | QDir.Hidden)
        exists = self.root.is_dir()
        if exists:
            self.model.setRootPath(str(self.root))
            self.tree.setModel(self.model)
            self.tree.setRootIndex(self.model.index(str(self.root)))
            self.tree.setColumnWidth(0, 500)
            self.tree.setColumnWidth(1, 110)
            self.tree.setColumnWidth(2, 150)
            self.tree.selectionModel().selectionChanged.connect(self.invalidate)
        else:
            # An invalid QModelIndex would expose the computer's drives instead.
            self.tree.setModel(None)
        self.file_browser.setCurrentWidget(self.tree if exists else self.missing_directory)
        self.preview_button.setEnabled(exists)
        if old is not None:
            old.deleteLater()
        self.preview.clear()
        self.invalidate()
        if not exists:
            self.status.setText('素材目录不存在；点击“打开素材目录”可创建，或在设置中更换保存目录。')

    def set_busy(self, busy):
        self.tree.setEnabled(not busy)
        self.refresh_button.setEnabled(not busy)
        self.preview_button.setEnabled(not busy and self.root.is_dir())
        self.delete_button.setEnabled(not busy and bool(self.plan and self.plan['batches']))

    def prepare(self):
        if not self.root.is_dir() or self.tree.selectionModel() is None:
            self.refresh()
            return
        if self.owner.work_in_progress():
            self.status.setText('请先完成或停止当前任务，再预览清理')
            return
        paths = [self.model.filePath(x) for x in self.tree.selectionModel().selectedRows()]
        if not paths:
            self.status.setText('请先选中文件或文件夹')
            return
        self.plan = None
        root, folders = self.root, list(self.owner.workspace.folders)
        self.owner.cleanup_busy = True
        self.set_busy(True)
        self.status.setText('正在核对文件归属和清理范围…')
        def completed(plan):
            if root != self.root:
                self.status.setText('素材目录已改变，请重新选择并预览')
                return
            self.plan = plan
            kinds = {'originals': '下载原片', 'products': '加工成品', 'staging': '上传暂存'}
            lines = [f"将删除 {plan['files']} 个文件，合计 {plan['bytes']/1048576:.1f} MB（逻辑大小）。",
                     '配套封面与成品一起删除。记录、配置及未登记文件不在清单内。', '']
            for batch in plan['batches']:
                for entry in batch['entries']:
                    lines.append(f"[{kinds[entry['kind']]}] {entry['path']}")
                    if entry.get('cover', {}).get('signature'):
                        lines.append('[配套封面] ' + entry['cover']['path'])
            lines.extend(plan['errors'])
            self.preview.setPlainText('\n'.join(lines))
            self.status.setText('清单已就绪 · 删除不经过回收站' if plan['batches'] else
                                '所选范围没有可清理的登记媒体；其他文件受保护')
        def finished():
            self.owner.cleanup_busy = False
            self.set_busy(False)
            self.owner.task_finished.emit()
        self.owner.cleanup_task = Background(lambda: plan_selection(root, folders, paths), self.owner)
        self.owner.cleanup_task.result.connect(completed)
        self.owner.cleanup_task.failed.connect(lambda msg: self.status.setText('预览失败：' + msg))
        self.owner.cleanup_task.finished.connect(finished)
        self.owner.cleanup_task.start()

    def confirm(self):
        if (not self.plan or self.owner.work_in_progress() or
                Path(self.plan.get('root', self.root)) != Path(self.owner.output_root).resolve()):
            self.status.setText('请等待当前任务结束，并重新预览')
            return
        if QMessageBox.question(self, '永久删除文件',
                f"将永久删除清单中的 {self.plan['files']} 个文件，并立即同步下载、加工和待上传列表。\n"
                '不经过回收站。上传暂存清理后需重新准备上传。是否继续？',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.owner.run_batch_cleanup([], 'managed', self.plan)
