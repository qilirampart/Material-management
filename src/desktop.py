from __future__ import annotations

import copy
import json
import shutil
import sys
import threading
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QProcess, QTimer, QLockFile
from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QStackedWidget, QLabel, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QComboBox, QLineEdit, QFileDialog, QMessageBox, QScrollArea, QProgressBar, QSpinBox,
)

from src.batch import LABELS, read_input, save_json, export_report
from src.media import (
    MINIMUM_VIDEO_BITRATE_KBPS,
    describe_bitrate,
    describe_video,
    effective_video_bitrate_bps,
    probe,
)
from src.paths import RESOURCE_ROOT, DATA_ROOT, prepare_environment
from src.upload import enhance_selected_bitrates
from src.vision import PHRASES, load_profile, fingerprint
from src.desktop_widgets import button, title, local_open, SettingsPage, ReviewPage, PlatformPage

from src.ui_design import STYLE, card, label, SettingsPage, Background
from src.task_input import links_to_rows, local_files_to_rows



def read_json(path, fallback):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return fallback


def probe_missing_quality(items):
    metadata = {}
    for video_id, path in items:
        try:
            metadata[video_id] = probe(path)
        except (OSError, ValueError, KeyError, RuntimeError):
            continue
    return metadata


def enhance_batch_bitrates(batch_folder, records, video_ids, progress=None, should_stop=None):
    batch_folder = Path(batch_folder).resolve()
    durable_records = copy.deepcopy(records)
    state_path = batch_folder / 'results.json'
    failed = {}

    def persist_item(video_id, values):
        if video_id not in durable_records:
            return
        durable_records[video_id].update(values)
        state = read_json(state_path, {})
        state['records'] = durable_records
        save_json(state_path, state)
        if progress:
            metadata = values.get('bitrate_enhanced_metadata', {})
            progress({
                'phase': 'completed',
                'video_id': video_id,
                'transcode': metadata.get('transcode', {}) if isinstance(metadata, dict) else {},
            })

    def record_failure(video_id, error):
        failed[video_id] = type(error).__name__
        if progress:
            progress({'phase': 'failed', 'video_id': video_id})

    def item_started(video_id, index, total):
        if progress:
            progress({
                'phase': 'started',
                'video_id': video_id,
                'index': index,
                'total': total,
            })

    def item_phase(video_id, phase):
        if progress:
            progress({
                'phase': phase,
                'video_id': video_id,
            })

    updates = enhance_selected_bitrates(
        durable_records,
        video_ids,
        batch_folder / 'bitrate-enhanced',
        item_completed=persist_item,
        item_failed=record_failure,
        item_started=item_started,
        item_phase=item_phase if progress else None,
        should_stop=should_stop,
    )
    return {
        'folder': str(batch_folder),
        'updates': updates,
        'failed': failed,
        'stopped': bool(should_stop and should_stop()),
    }


class MainWindow(QMainWindow):
    def __init__(self, restore=True):
        super().__init__()
        self.setWindowTitle("点众 · 素材投放助手")
        self.resize(1366, 840)
        self.setMinimumSize(980, 680)
        self.config_path = DATA_ROOT / "runtime" / "desktop_config.json"
        self.config = json.loads((RESOURCE_ROOT / "config.example.json").read_text(encoding="utf-8"))
        self.config.update(read_json(self.config_path, {}))
        self.config.setdefault("output_root", str(DATA_ROOT / "output"))
        self.rows, self.records, self.notes = [], {}, {}
        self.checked = set()
        self.io_task = None
        self.quality_task = None
        self.bitrate_task = None
        self.bitrate_stop_event = threading.Event()
        self.folder = None
        self.input_path = None
        self.current_id = ""
        self.current_stage = ""
        self.batch_task_ids = []
        self.process = None
        self.batch_lock = None
        self.close_after = False
        self.event_offset = 0
        self.current_fingerprint = None
        self.runtime = DATA_ROOT / "runtime"
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.event_timer = QTimer(self)
        self.event_timer.setInterval(350)
        self.event_timer.timeout.connect(self.poll_events)
        outer = QWidget()
        self.setCentralWidget(outer)
        shell = QHBoxLayout(outer)
        shell.setContentsMargins(0, 0, 0, 0)
        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setFixedWidth(190)
        self.navigation.addItems(["▤   素材任务", "◇   检测复核", "▦   平台工作台", "⚙   设置"])
        rail = QWidget()
        rail.setObjectName('rail')
        rail.setFixedWidth(190)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(0, 0, 0, 0)
        brand = QLabel('D  点众\n    素材投放助手')
        brand.setObjectName('brand')
        rail_layout.addWidget(brand)
        rail_layout.addWidget(self.navigation, 1)
        shell.addWidget(rail)
        self.pages = QStackedWidget()
        shell.addWidget(self.pages, 1)
        self.build_tasks()
        self.review = ReviewPage()
        self.review.picked.connect(self.show_review_id)
        self.review.note_saved.connect(self.save_note)
        self.review.recheck.connect(lambda id_: self.start_batch([id_], True))
        self.add_page(self.review)
        self.platform = PlatformPage(self.config)
        self.add_page(self.platform)
        self.settings = SettingsPage(self.config)
        self.settings.saved.connect(self.save_settings)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.settings)
        self.pages.addWidget(scroll)
        self.navigation.currentRowChanged.connect(self.change_page)
        self.navigation.setCurrentRow(0)
        self.statusBar().showMessage("就绪 · 导入需求表开始 · 内部平台上传尚未接入")
        if restore and self.config.get('restore_batch', True):
            last = self.config.get("last_batch", "")
            if not last and (DATA_ROOT / "output/pilot/results.json").exists():
                last = str(DATA_ROOT / "output/pilot")
            if last and (Path(last) / "results.json").is_file():
                self.open_batch(Path(last))

    def add_page(self, widget):
        widget.layout().setContentsMargins(22, 18, 22, 18)
        self.pages.addWidget(widget)

    def build_tasks(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = QHBoxLayout()
        heading.addWidget(title('素材任务'), 1)
        self.open_button = button('历史批次', self.choose_batch)
        heading.addWidget(self.open_button)
        heading.addWidget(button('新建批次', self.new_batch))
        layout.addLayout(heading)
        layout.addWidget(label('导入素材，勾选后开始处理'))
        body = QHBoxLayout()
        left = QVBoxLayout()
        add, box = card('添加素材')
        inputs = QHBoxLayout()
        self.import_button = button('导入 Excel', self.import_excel)
        inputs.addWidget(self.import_button)
        self.link_input = QLineEdit()
        self.link_input.setPlaceholderText('粘贴抖音分享链接或文字，可包含多条链接')
        inputs.addWidget(self.link_input, 1)
        self.link_button = button('加入候选区', self.add_links, True)
        inputs.addWidget(self.link_button)
        self.local_button = button('添加本地视频', self.add_local)
        inputs.addWidget(self.local_button)
        box.addLayout(inputs)
        self.batch_name = label('尚未添加素材 · 导入仅加入候选区，不自动执行')
        box.addWidget(self.batch_name)
        left.addWidget(add)
        candidates, box = card()
        filters = QHBoxLayout()
        filters.addWidget(label('候选素材', 'section'), 1)
        self.filter = QComboBox()
        self.filter.addItem('全部状态', 'all')
        for key, value in LABELS.items():
            self.filter.addItem(value, key)
        self.filter.addItem('规则已更新', 'stale')
        filters.addWidget(self.filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索剧名 / 视频 ID / 原视频链接')
        filters.addWidget(self.search)
        box.addLayout(filters)
        selection_toolbar = QHBoxLayout()
        self.select_all_button = button('全选', lambda: self.check_visible(True))
        self.invert_button = button('反选', self.invert_visible_selection)
        self.clear_selection_button = button('清除选择', self.clear_selection)
        self.remove_selection_button = button('移除选中', self.remove_checked_rows)
        for control in (
            self.select_all_button,
            self.invert_button,
            self.clear_selection_button,
            self.remove_selection_button,
        ):
            selection_toolbar.addWidget(control)
        selection_toolbar.addWidget(label('前 N 条'))
        self.selection_count = QSpinBox()
        self.selection_count.setRange(1, 100000)
        self.selection_count.setValue(10)
        self.selection_count.setFixedWidth(76)
        selection_toolbar.addWidget(self.selection_count)
        self.select_first_button = button('选择前 N 条', self.select_first_rows)
        self.select_to_end_button = button('选择至末尾', self.select_from_current_to_end)
        self.select_first_button.setToolTip('在当前筛选结果中选择前 N 条')
        self.select_to_end_button.setToolTip('从当前聚焦行开始，选择到当前筛选结果末尾')
        selection_toolbar.addWidget(self.select_first_button)
        selection_toolbar.addWidget(self.select_to_end_button)
        selection_toolbar.addStretch()
        box.addLayout(selection_toolbar)
        toolbar = QHBoxLayout()
        self.selection_label = label('已勾选 0 条')
        toolbar.addWidget(self.selection_label, 1)
        self.bitrate_button = button('提升选中低码率视频', self.enhance_selected_bitrate)
        self.bitrate_button.setToolTip('只处理当前勾选且不超过 3500 kbps 的视频；原始下载文件保持不变')
        toolbar.addWidget(self.bitrate_button)
        self.mode = QComboBox()
        self.mode.addItem('下载并检测', 'both')
        self.mode.addItem('仅下载', 'download')
        self.mode.addItem('仅检测', 'detect')
        toolbar.addWidget(self.mode)
        self.start_button = button('处理勾选素材', self.start_or_pause, True)
        toolbar.addWidget(self.start_button)
        box.addLayout(toolbar)
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels([
            '勾选', '编号', '视频 ID', '素材', '原视频链接',
            '下载状态', '视频信息', '检测状态', '命中项 / 提示', '人工备注',
        ])
        self.table.horizontalHeaderItem(6).setText('码率 / 视频信息')
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(55)
        for index, width in enumerate([78, 62, 190, 158, 300, 90, 250, 138, 150, 130]):
            self.table.setColumnWidth(index, width)
        self.table.horizontalHeader().moveSection(6, 4)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellDoubleClicked.connect(lambda row, col: self.open_selected())
        self.table.itemChanged.connect(self.check_changed)
        self.table.itemSelectionChanged.connect(self.preview_selected)
        self.filter.currentIndexChanged.connect(self.apply_filter)
        self.search.textChanged.connect(self.apply_filter)
        box.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.retry_button = button('重试勾选失败项', self.retry_failed)
        self.recheck_button = button('重检勾选素材', self.recheck_selected)
        self.export_button = button('导出结果', self.export)
        for w in [self.retry_button, self.recheck_button, self.export_button]:
            actions.addWidget(w)
        actions.addStretch()
        box.addLayout(actions)
        self.summary = label('尚无素材')
        self.summary.setObjectName('summary')
        box.addWidget(self.summary)
        left.addWidget(candidates, 1)
        body.addLayout(left, 1)
        self.task_side = QWidget()
        side = QVBoxLayout(self.task_side)
        side.setContentsMargins(0, 0, 0, 0)
        self.task_side.setFixedWidth(260)
        work, box = card('后台任务')
        self.work_status = label('就绪 · 并发上限 1', 'section')
        box.addWidget(self.work_status)
        self.work_detail = label('勾选候选素材后开始处理。\n任务在独立进程中排队执行。')
        box.addWidget(self.work_detail)
        self.download_bar = QProgressBar()
        self.download_bar.setRange(0, 1000)
        self.download_bar.setValue(0)
        self.download_bar.setFormat('等待下载')
        self.download_bar.setMinimumHeight(20)
        box.addWidget(self.download_bar)
        self.transfer_detail = label('下载时显示实际字节进度')
        box.addWidget(self.transfer_detail)
        self.pause_button = button('暂停队列', self.pause_active_task)
        box.addWidget(self.pause_button)
        box.addWidget(label('暂停后等待当前任务结束'))
        side.addWidget(work)
        proof, box = card('片头证据')
        self.preview = QLabel('选择一条素材查看证据')
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(200)
        box.addWidget(self.preview)
        self.preview_text = label('尚无检测结果')
        box.addWidget(self.preview_text)
        box.addWidget(button('查看证据', self.open_selected))
        box.addWidget(label('仅抽检片头三帧，不代表全片审核通过。'))
        side.addWidget(proof)
        side.addStretch()
        body.addWidget(self.task_side)
        layout.addLayout(body, 1)
        self.add_page(page)
        self.set_busy(False)

    def new_batch(self):
        if self.is_running() or self.has_active_background_tasks():
            self.statusBar().showMessage('后台任务仍在运行，完成后才能新建批次')
            return
        self.rows, self.records, self.notes = [], {}, {}
        self.checked.clear()
        self.folder = self.input_path = None
        self.batch_name.setText('新批次 · 添加素材后勾选处理')
        self.refresh_table()

    def check_changed(self, cell):
        if cell.column() != 0:
            return
        id_ = cell.data(Qt.UserRole)
        is_checked = cell.checkState() == Qt.Checked
        if is_checked:
            self.checked.add(id_)
        else:
            self.checked.discard(id_)
        self.table.blockSignals(True)
        cell.setText('已选择' if is_checked else '选择')
        cell.setForeground(QColor('#0F766E' if is_checked else '#64727B'))
        font = cell.font()
        font.setBold(is_checked)
        cell.setFont(font)
        self.table.blockSignals(False)
        self.selection_label.setText(f'已勾选 {len(self.checked)} 条')
        self.bitrate_button.setEnabled(bool(self.checked) and not self.is_running())

    def sync_selection_cells(self):
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        for index, row in enumerate(self.rows):
            cell = self.table.item(index, 0)
            if cell is None:
                continue
            is_checked = row['video_id'] in self.checked and not row['input_error']
            cell.setCheckState(Qt.Checked if is_checked else Qt.Unchecked)
            cell.setText(
                '不可选' if row['input_error'] else ('已选择' if is_checked else '选择')
            )
            cell.setForeground(QColor('#0F766E' if is_checked else '#64727B'))
            font = cell.font()
            font.setBold(is_checked)
            cell.setFont(font)
        self.table.setUpdatesEnabled(True)
        self.table.blockSignals(False)
        self.selection_label.setText(f'已勾选 {len(self.checked)} 条')
        bitrate_running = self.bitrate_task and self.bitrate_task.isRunning()
        self.bitrate_button.setEnabled(
            not self.is_running() and not bitrate_running and bool(self.checked)
        )

    def check_visible(self, enabled):
        if not enabled:
            self.checked.clear()
        for i, row in enumerate(self.rows):
            if not self.table.isRowHidden(i) and not row['input_error']:
                if enabled:
                    self.checked.add(row['video_id'])
        self.sync_selection_cells()

    def visible_selectable_rows(self):
        return [
            index for index, row in enumerate(self.rows)
            if not self.table.isRowHidden(index) and not row['input_error']
        ]

    def clear_selection(self):
        self.checked.clear()
        self.sync_selection_cells()

    def invert_visible_selection(self):
        for index in self.visible_selectable_rows():
            video_id = self.rows[index]['video_id']
            if video_id in self.checked:
                self.checked.remove(video_id)
            else:
                self.checked.add(video_id)
        self.sync_selection_cells()

    def _replace_visible_selection(self, selected_rows):
        visible_rows = self.visible_selectable_rows()
        self.checked.difference_update(self.rows[index]['video_id'] for index in visible_rows)
        self.checked.update(self.rows[index]['video_id'] for index in selected_rows)
        self.sync_selection_cells()

    def select_first_rows(self):
        visible_rows = self.visible_selectable_rows()
        self._replace_visible_selection(visible_rows[:self.selection_count.value()])

    def select_from_current_to_end(self):
        visible_rows = self.visible_selectable_rows()
        if not visible_rows:
            return
        current = self.table.currentRow()
        start = visible_rows.index(current) if current in visible_rows else 0
        self._replace_visible_selection(visible_rows[start:])

    def remove_checked_rows(self):
        if self.is_running() or not self.checked:
            return
        removed = {row['video_id'] for row in self.rows if row['video_id'] in self.checked}
        self.rows = [row for row in self.rows if row['video_id'] not in removed]
        self.checked.clear()
        self.persist_candidate_rows()
        self.refresh_table()
        if self.folder:
            self.batch_name.setText(
                f'当前批次：{self.folder.name} · {len(self.rows)} 条素材 · 导入不自动执行'
            )
        self.statusBar().showMessage(f'已从候选区移除 {len(removed)} 条素材，本地视频文件未删除。')

    def persist_candidate_rows(self):
        if not self.folder or not self.input_path:
            return
        save_json(self.input_path, self.rows)
        from src.batch import file_hash
        state_path = self.folder / 'results.json'
        state = read_json(state_path, {})
        state.update({
            'input_path': str(self.input_path),
            'input_sha256': file_hash(self.input_path),
            'input_rows': self.rows,
            'records': self.records,
        })
        save_json(state_path, state)

    def preview_selected(self):
        ids = self.focused_ids()
        if not ids or not hasattr(self, 'preview'):
            return
        record = self.records.get(ids[0], {})
        frames = record.get('frames', [])
        from PySide6.QtGui import QPixmap
        self.preview.clear()
        if frames:
            self.preview.setPixmap(QPixmap(frames[0]['path']).scaled(210, 245, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.preview.setText('尚无片头证据')
        self.preview_text.setText('、'.join(h['match'] for h in record.get('hits', [])) or LABELS.get(record.get('status'), '尚未检测'))

    def add_links(self):
        try:
            self.add_candidates(links_to_rows(self.link_input.text()))
            self.link_input.clear()
        except ValueError as exc:
            self.statusBar().showMessage(str(exc))

    def add_local(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '添加本地视频', '', '视频 (*.mp4 *.mov *.mkv *.avi *.webm)')
        if paths:
            self.add_candidates(local_files_to_rows(paths))

    def add_candidates(self, rows, original=None):
        if self.is_running():
            return
        if not rows:
            raise ValueError('没有素材记录')
        if self.folder is None:
            self.folder = Path(self.config['output_root']) / (datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:4])
            self.folder.mkdir(parents=True, exist_ok=True)
        if original:
            dest = self.folder / ('source-' + uuid.uuid4().hex[:6] + '.xlsx')
            shutil.copy2(original, dest)
        existing = {r['video_id'] for r in self.rows if not r['input_error']}
        for row in rows:
            if row['input_error'] or row['video_id'] not in existing:
                self.rows.append(row)
                existing.add(row['video_id'])
        self.input_path = self.folder / 'input.json'
        save_json(self.input_path, self.rows)
        from src.batch import file_hash
        save_json(self.folder / 'results.json', {'input_path': str(self.input_path), 'input_sha256': file_hash(self.input_path), 'input_rows': self.rows, 'records': self.records})
        self.config['last_batch'] = str(self.folder)
        save_json(self.config_path, self.config)
        self.batch_name.setText(f'当前批次：{self.folder.name} · {len(self.rows)} 条素材 · 导入不自动执行')
        self.refresh_table()
        self.statusBar().showMessage('已加入候选区，请勾选需要处理的素材。')

    def change_page(self, index):
        self.pages.setCurrentIndex(index)
        if index == 1:
            self._populate_review_materials()
        if index == 2:
            self.platform.set_materials(self.rows, self.records, self.notes, self.checked, self.folder)
        if index != 1:
            self.review.player.pause()

    def _populate_review_materials(self):
        self.review.materials.clear()
        from PySide6.QtWidgets import QListWidgetItem
        for index, row in enumerate(self.rows, 1):
            drama = str(row['source']['剧名'] or '')
            item = QListWidgetItem(
                f"编号 {index} · {drama}\n{row['video_id']}\n{self.effective_status(row)[1]}"
            )
            item.setData(Qt.UserRole, row['video_id'])
            self.review.materials.addItem(item)

    def is_running(self):
        return self.process is not None and self.process.state() != QProcess.NotRunning

    def active_background_tasks(self):
        tasks = [self.io_task, self.quality_task, self.bitrate_task, self.settings.testing]
        tasks.extend(self.platform.active_background_tasks())
        return [task for task in tasks if task is not None and task.isRunning()]

    def has_active_background_tasks(self):
        return bool(self.active_background_tasks())

    def set_busy(self, busy):
        for control in [
            self.import_button, self.open_button, self.retry_button, self.recheck_button,
            self.mode, self.bitrate_button, self.link_button, self.local_button, self.select_all_button,
            self.invert_button, self.clear_selection_button, self.remove_selection_button,
            self.selection_count, self.select_first_button, self.select_to_end_button,
        ]:
            control.setEnabled(not busy)
        if hasattr(self, "settings"):
            self.settings.setEnabled(not busy)
        self.start_button.setText("暂停（当前素材结束后）" if busy else "处理勾选素材")
        self.start_button.setEnabled(True)

    def selected_ids(self):
        return [r['video_id'] for i, r in enumerate(self.rows) if r['video_id'] in self.checked and not r['input_error'] and not self.table.isRowHidden(i)]

    def focused_ids(self):
        return [self.table.item(index.row(), 0).data(Qt.UserRole) for index in self.table.selectionModel().selectedRows()
                if not self.table.isRowHidden(index.row())]

    def effective_status(self, row):
        id_ = row["video_id"]
        record = self.records.get(id_, {})
        if row["input_error"]:
            return "invalid_input", LABELS["invalid_input"]
        if self.notes.get(id_, {}).get("blocked"):
            return "blocked", "人工确认拦截"
        status = record.get("status", "pending")
        if status == "sample_clear" and self.current_fingerprint and record.get("fingerprint") != self.current_fingerprint:
            return "stale", "规则已更新，需重检"
        return status, LABELS.get(status, "待复核")

    def refresh_table(self):
        selected = set(self.focused_ids())
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        scroll = self.table.verticalScrollBar().value()
        self.table.setRowCount(len(self.rows))
        counts = Counter()
        downloads = 0
        for index, row in enumerate(self.rows):
            id_ = row["video_id"]
            record = self.records.get(id_, {})
            status, label = self.effective_status(row)
            counts[status] += 1
            downloads += record.get("download") == "已下载"
            if id_ == self.current_id:
                label = self.current_stage + "…"
            hints = "、".join(dict.fromkeys(h["match"] for h in record.get("hits", []))) or row["input_error"] or record.get("reason", "")
            source = row.get('source', {})
            original_url = str(row.get('url') or source.get('原始链接') or '')
            is_checked = id_ in self.checked
            quality_parts = [
                describe_bitrate(record.get("metadata")),
                describe_video(record.get("metadata")),
            ]
            enhanced_path = Path(record.get('bitrate_enhanced_path', ''))
            if enhanced_path.is_file():
                quality_parts.append(
                    '达标副本 ' + describe_bitrate(record.get('bitrate_enhanced_metadata'))
                )
            transcode = record.get('bitrate_enhanced_metadata', {}).get('transcode', {})
            if enhanced_path.is_file() and isinstance(transcode, dict) and transcode.get('total_seconds') is not None:
                encoder = str(transcode.get('video_encoder') or '未知编码器')
                device = 'GPU' if transcode.get('hardware_accelerated') else 'CPU'
                quality_parts.append(f'转码 {device}/{encoder} {float(transcode["total_seconds"]):.1f} 秒')
            cells = [
                '不可选' if row['input_error'] else ('已选择' if is_checked else '选择'),
                str(index + 1),
                id_,
                str(source.get("剧名") or ""),
                original_url,
                record.get("download", "待下载"),
                " | ".join(filter(None, quality_parts)),
                label,
                hints,
                self.notes.get(id_, {}).get("note", ""),
            ]
            for col, value in enumerate(cells):
                cell = self.table.item(index, col)
                if cell is None:
                    cell = QTableWidgetItem()
                    self.table.setItem(index, col, cell)
                if cell.text() != value:
                    cell.setText(value)
                cell.setToolTip(value)
                if col == 0:
                    cell.setFlags(cell.flags() | Qt.ItemIsUserCheckable)
                    if row['input_error']:
                        cell.setFlags(cell.flags() & ~Qt.ItemIsUserCheckable)
                    cell.setCheckState(Qt.Checked if is_checked else Qt.Unchecked)
                    cell.setData(Qt.UserRole, id_)
                    cell.setData(Qt.UserRole + 1, status)
                    cell.setTextAlignment(Qt.AlignCenter)
                    cell.setForeground(QColor('#0F766E' if is_checked else '#64727B'))
                    font = cell.font()
                    font.setBold(is_checked)
                    cell.setFont(font)
                if col in (1, 2):
                    cell.setTextAlignment(Qt.AlignCenter)
                if col == 6:
                    cell.setForeground(QColor(
                        '#116d62' if '达标' in value else '#b94035' if '不足' in value else '#64727b'
                    ))
                if col == 7:
                    cell.setForeground(QColor({"blocked": "#b94035", "sample_clear": "#116d62", "pending": "#64727b"}.get(status, "#986016")))
            if id_ in selected:
                from PySide6.QtCore import QItemSelectionModel
                self.table.selectionModel().select(self.table.model().index(index, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
        self.summary.setText(f"{len(self.rows)} 条记录    已下载 {downloads}    抽检未发现 {counts['sample_clear']}    命中 {counts['blocked']}    待复核/失败 {counts['review_required'] + counts['download_failed']}    待处理 {counts['pending']}    规则更新 {counts['stale']}")
        self.table.blockSignals(False)
        self.table.setUpdatesEnabled(True)
        self.selection_label.setText(f'已勾选 {len(self.checked)} 条')
        bitrate_running = self.bitrate_task and self.bitrate_task.isRunning()
        self.bitrate_button.setEnabled(not self.is_running() and not bitrate_running and bool(self.checked))
        self.apply_filter()
        self.table.verticalScrollBar().setValue(scroll)

    def apply_filter(self):
        state = self.filter.currentData()
        query = self.search.text().strip().casefold()
        for index in range(self.table.rowCount()):
            cell = self.table.item(index, 0)
            if not cell:
                continue
            matches = state == "all" or cell.data(Qt.UserRole + 1) == state
            text = " ".join(
                self.table.item(index, column).text()
                for column in (2, 3, 4)
            )
            self.table.setRowHidden(index, not (matches and query in text.casefold()))

    def import_excel(self):
        path, _ = QFileDialog.getOpenFileName(self, '导入需求表', str(DATA_ROOT), 'Excel (*.xlsx)')
        if not path or (self.io_task and self.io_task.isRunning()):
            return
        self.set_busy(True)
        self.start_button.setEnabled(False)
        self.statusBar().showMessage('正在后台读取表格…')
        self.io_task = Background(lambda: read_input(path), self)
        self.io_task.result.connect(lambda rows: self.add_candidates(rows, path))
        self.io_task.failed.connect(self.statusBar().showMessage)
        self.io_task.finished.connect(lambda: self.set_busy(False))
        self.io_task.start()

    def choose_batch(self):
        if self.is_running() or self.has_active_background_tasks():
            self.statusBar().showMessage('后台任务仍在运行，完成后才能打开历史批次')
            return
        path, _ = QFileDialog.getOpenFileName(self, "打开批次结果", self.config["output_root"], "批次结果 (results.json)")
        if path:
            self.open_batch(Path(path).parent)

    def open_batch(self, folder):
        if self.is_running() or self.has_active_background_tasks():
            self.statusBar().showMessage('后台任务仍在运行，完成后才能切换批次')
            return
        try:
            state = json.loads((folder / "results.json").read_text(encoding="utf-8"))
            if not isinstance(state.get("input_rows"), list) or not isinstance(state.get("records"), dict):
                raise ValueError("不是有效的素材批次文件。")
            self.checked.clear()
            self.folder = folder.resolve()
            self.rows, self.records = state["input_rows"], state["records"]
            stored = state.get("input_path")
            self.input_path = Path(stored) if stored else None
            if not self.input_path or not self.input_path.exists():
                # Compatibility with the existing pilot generated before the desktop UI.
                from src.batch import file_hash
                candidates = [self.folder / "input.xlsx", *DATA_ROOT.glob("*.xlsx")]
                self.input_path = next((p for p in candidates if p.is_file() and file_hash(p) == state.get("input_sha256")), None)
            self.notes = read_json(self.folder / "reviews.json", {})
            self.config["last_batch"] = str(self.folder)
            save_json(self.config_path, self.config)
            drama = self.rows[0]["source"]["剧名"] if self.rows else "空批次"
            self.batch_name.setText(f"{drama}  ·  {self.folder.name}")
            self.refresh_fingerprint()
            self.refresh_table()
            self.refresh_missing_quality_metadata()
            if self.rows:
                row = self.rows[0]
                self.review.show_record(row, self.records.get(row["video_id"], {}), self.notes.get(row["video_id"], {}), self.effective_status(row)[1])
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.warning(self, "打开失败", str(exc))

    def refresh_fingerprint(self):
        try:
            logo = Path(self.config.get("logo_reference", "assets/references/hongguo_logo.png"))
            if not logo.is_absolute():
                logo = RESOURCE_ROOT / logo
            self.current_fingerprint = fingerprint(load_profile(self.config), logo, self.config.get("phrases", PHRASES))
        except (OSError, ValueError, KeyError):
            self.current_fingerprint = None

    def refresh_missing_quality_metadata(self):
        if self.quality_task and self.quality_task.isRunning():
            return
        pending = []
        for video_id, record in self.records.items():
            path = Path(record.get('video_path', ''))
            if (
                record.get('download') == '已下载'
                and path.is_file()
                and effective_video_bitrate_bps(record.get('metadata')) <= 0
            ):
                pending.append((video_id, str(path)))
        if not pending or not self.folder:
            return
        batch_folder = self.folder.resolve()
        self.statusBar().showMessage(f'正在后台读取 {len(pending)} 个视频的码率…')
        self.quality_task = Background(
            lambda: {
                'folder': str(batch_folder),
                'metadata': probe_missing_quality(pending),
            },
            self,
        )
        self.quality_task.result.connect(self.apply_quality_metadata)
        self.quality_task.start()

    def apply_quality_metadata(self, result):
        if not self.folder or result.get('folder') != str(self.folder.resolve()):
            return
        updates = result.get('metadata', {})
        for video_id, metadata in updates.items():
            if video_id in self.records:
                self.records[video_id]['metadata'] = metadata
        if updates:
            state_path = self.folder / 'results.json'
            state = read_json(state_path, {})
            state['records'] = self.records
            save_json(state_path, state)
            self.refresh_table()
        self.statusBar().showMessage(f'已读取 {len(updates)} 个视频的码率信息')

    def enhance_selected_bitrate(self):
        if self.bitrate_task and self.bitrate_task.isRunning():
            return
        selected = self.selected_ids()
        low_bitrate_ids = [
            video_id for video_id in selected
            if 0 < effective_video_bitrate_bps(self.records.get(video_id, {}).get('metadata'))
            <= MINIMUM_VIDEO_BITRATE_KBPS * 1000
        ]
        if not low_bitrate_ids:
            self.statusBar().showMessage('当前勾选素材中没有已读取码率且不达标的视频')
            return
        batch_folder = self.folder.resolve()
        records = copy.deepcopy(self.records)
        self.bitrate_stop_event.clear()
        self.set_busy(True)
        self.start_button.setEnabled(False)
        self.work_status.setText('正在提升码率 · 并发上限 1')
        self.work_detail.setText(f'准备处理 {len(low_bitrate_ids)} 个低码率视频')
        self.download_bar.setRange(0, 0)
        self.download_bar.setFormat('正在转码')
        self.statusBar().showMessage(f'正在提升 {len(low_bitrate_ids)} 个视频的码率…')
        task = None

        def enhance():
            return enhance_batch_bitrates(
                batch_folder,
                records,
                low_bitrate_ids,
                progress=task.progress.emit,
                should_stop=self.bitrate_stop_event.is_set,
            )

        task = Background(enhance, self)
        self.bitrate_task = task
        self.bitrate_task.progress.connect(self.show_bitrate_progress)
        self.bitrate_task.result.connect(self.apply_enhanced_bitrates)
        self.bitrate_task.failed.connect(self.bitrate_enhancement_failed)
        self.bitrate_task.finished.connect(self.bitrate_enhancement_finished)
        self.bitrate_task.start()

    def show_bitrate_progress(self, event):
        phase = event.get('phase')
        if phase == 'completed':
            details = event.get('transcode', {})
            if not isinstance(details, dict) or details.get('total_seconds') is None:
                return
            encoder = str(details.get('video_encoder') or '未知编码器')
            device = 'GPU' if details.get('hardware_accelerated') else 'CPU'
            encoding = float(details.get('encoding_seconds') or 0)
            validation = float(details.get('validation_seconds') or 0)
            total = float(details.get('total_seconds') or 0)
            self.work_detail.setText(
                f"{event.get('video_id', '')}\n"
                f"已完成：{device}/{encoder} · 编码 {encoding:.1f} 秒 · 校验 {validation:.1f} 秒 · 总计 {total:.1f} 秒"
            )
            return
        if phase in {'encoding', 'validating'}:
            phase_text = '正在编码达标副本' if phase == 'encoding' else '正在完整复检输出文件'
            self.work_detail.setText(
                f"{event.get('video_id', '')}\n{phase_text}"
            )
            return
        if phase != 'started':
            return
        index = int(event.get('index', 0))
        total = max(1, int(event.get('total', 1)))
        self.download_bar.setRange(0, total)
        self.download_bar.setValue(max(0, index - 1))
        self.download_bar.setFormat(f'第 {index} / {total} 个')
        self.work_detail.setText(
            f"正在处理 {event.get('video_id', '')}\n当前文件完成后可暂停"
        )

    def apply_enhanced_bitrates(self, result):
        if not self.folder or result.get('folder') != str(self.folder.resolve()):
            return
        updates = result.get('updates', {})
        failed = result.get('failed', {})
        for video_id, values in updates.items():
            if video_id in self.records:
                self.records[video_id].update(values)
        self.refresh_table()
        message = f'已完成 {len(updates)} 个低码率视频的达标副本'
        if failed:
            message += f'，{len(failed)} 个失败，可重新勾选重试'
        if result.get('stopped'):
            message += '，队列已暂停'
        self.statusBar().showMessage(message)

    def bitrate_enhancement_failed(self, message):
        self.statusBar().showMessage(f'码率提升失败：{message}')

    def bitrate_enhancement_finished(self):
        self.pause_button.setEnabled(True)
        self.work_status.setText('就绪 · 并发上限 1')
        self.work_detail.setText('码率处理结束；达标副本将在上传时自动使用。')
        self.download_bar.setRange(0, 1000)
        self.download_bar.setValue(1000)
        self.download_bar.setFormat('码率处理结束')
        self.set_busy(False)

    def show_review_id(self, id_):
        row = next((r for r in self.rows if r['video_id'] == id_), None)
        if row:
            self.review.show_record(row, self.records.get(id_, {}), self.notes.get(id_, {}), self.effective_status(row)[1])

    def open_selected(self):
        ids = self.focused_ids()
        if not ids:
            return
        self._populate_review_materials()
        row = next(r for r in self.rows if r["video_id"] == ids[0])
        self.review.show_record(row, self.records.get(ids[0], {}), self.notes.get(ids[0], {}), self.effective_status(row)[1])
        self.navigation.setCurrentRow(1)

    def save_note(self, id_, note, blocked):
        if not self.folder:
            return
        self.notes[id_] = {"note": note, "blocked": blocked, "updated_at": datetime.now().isoformat()}
        save_json(self.folder / "reviews.json", self.notes)
        self.refresh_table()
        self.statusBar().showMessage("复核记录已保存；自动检测证据保持可追溯")

    def save_settings(self, config):
        self.config = config
        self.platform.config = config
        self.platform.address.setText(config.get("platform_url", ""))
        save_json(self.config_path, config)
        self.refresh_fingerprint()
        self.refresh_table()

    def export(self):
        if not self.folder:
            return
        records = copy.deepcopy(self.records)
        for row in self.rows:
            id_ = row["video_id"]
            record = records.setdefault(id_, {})
            status, _ = self.effective_status(row)
            if status == "stale":
                record.update(status="review_required", reason="规则已更新，需重新检测")
            elif self.notes.get(id_, {}).get("blocked"):
                record.update(status="blocked")
            note = self.notes.get(id_, {}).get("note", "")
            if note:
                record["reason"] = record.get("reason", "") + "\n人工备注：" + note
        try:
            path = self.folder / "复核结果.xlsx"
            export_report(self.rows, records, path)
            self.statusBar().showMessage("已导出：" + str(path))
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", "请关闭已打开的结果表后重试。\n" + str(exc))

    def start_or_pause(self):
        if self.is_running():
            self.pause()
        else:
            self.start_batch()

    def retry_failed(self):
        ids = [r["video_id"] for r in self.rows if r["video_id"] in self.selected_ids() and self.records.get(r["video_id"], {}).get("status") in {"download_failed", "review_required"}]
        self.start_batch(ids)

    def recheck_selected(self):
        ids = self.selected_ids()
        if ids:
            self.start_batch(ids, True)
        else:
            self.statusBar().showMessage("请先选中需要重新检测的素材")

    def start_batch(self, selected=None, force=False):
        if self.is_running() or self.has_active_background_tasks():
            self.statusBar().showMessage('后台任务仍在运行，完成后才能开始处理')
            return
        if not self.folder or not self.input_path:
            QMessageBox.information(self, "尚未准备批次", "请导入需求表，或打开含原始输入文件的历史批次。")
            return
        if selected == []:
            self.statusBar().showMessage("没有需要重试的素材")
            return
        if selected is None:
            selected = self.selected_ids()
        if not selected:
            self.statusBar().showMessage("当前批次没有待处理素材；可选中素材后点击重新检测")
            return
        operation = 'detect' if force else self.mode.currentData()
        self.batch_task_ids = list(dict.fromkeys(selected))
        download_only = operation == 'download'
        if not download_only:
            try:
                load_profile(self.config)
            except (OSError, ValueError, KeyError) as exc:
                QMessageBox.warning(self, "模型未配置", str(exc))
                self.navigation.setCurrentRow(3)
                return
        self.batch_lock = QLockFile(str(self.folder / ".desktop.lock"))
        if not self.batch_lock.tryLock(0):
            QMessageBox.warning(self, "批次正在使用", "另一软件窗口正在处理此批次。")
            return
        token = uuid.uuid4().hex
        self.request_path = self.runtime / f"job-{token}.json"
        self.stop_path = self.runtime / f"job-{token}.stop"
        self.event_path = self.request_path.with_suffix(".events.jsonl")
        self.event_offset = 0
        save_json(self.request_path, {"input_path": str(self.input_path), "output": str(self.folder), "config": self.config,
                                     "resume": True, "operation": operation, "selected_ids": list(dict.fromkeys(selected)),
                                     "force_review": force, "stop_file": str(self.stop_path)})
        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(RESOURCE_ROOT))
        self.process.finished.connect(self.worker_finished)
        self.process.errorOccurred.connect(self.worker_error)
        if getattr(sys, "frozen", False):
            program, args = sys.executable, ["--worker", str(self.request_path)]
        else:
            program, args = sys.executable, ["-m", "src.worker", str(self.request_path)]
        self.set_busy(True)
        self.work_status.setText(f"等待处理 0 / 共 {len(self.batch_task_ids)}")
        self.process.start(program, args)
        self.event_timer.start()
        self.statusBar().showMessage(f"后台任务已启动 · {len(set(selected))} 条素材")

    def pause(self):
        self.stop_path.write_text("pause", encoding="utf-8")
        self.start_button.setText("正在暂停…")
        self.start_button.setEnabled(False)
        self.statusBar().showMessage("当前素材处理完成后暂停；已完成结果将保留")

    def pause_active_task(self):
        if self.bitrate_task and self.bitrate_task.isRunning():
            self.bitrate_stop_event.set()
            self.pause_button.setEnabled(False)
            self.statusBar().showMessage('已请求暂停，当前视频完成后暂停')
            return
        if self.is_running():
            self.pause()

    def poll_events(self):
        if not self.event_path.exists():
            return
        with self.event_path.open("rb") as handle:
            handle.seek(self.event_offset)
            data = handle.read()
        complete = data.rfind(b"\n")
        if complete < 0:
            return
        self.event_offset += complete + 1
        for line in data[:complete].splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            kind = event.get("type")
            if kind == "saved":
                state = read_json(self.folder / "results.json", {})
                self.records = state.get("records", self.records)
                self.current_id = ""
                self.refresh_table()
            elif kind == "progress":
                self.current_id = event["video_id"]
                self.current_stage = event["stage"]
                self.show_task_position(event)
                self.work_detail.setText(self.current_id + "\n" + self.current_stage)
                self.download_bar.setRange(0, 0)
                self.transfer_detail.setText(self.current_stage + '…')
                self.show_stage_progress(self.current_id, self.current_stage)
                self.statusBar().showMessage(self.current_id + " · " + self.current_stage)
            elif kind == 'download_progress':
                self.show_download_progress(event)
            elif kind in {"paused", "finished"}:
                self.statusBar().showMessage("已暂停，可继续" if kind == "paused" else "本轮任务结束，结果已保存")
            elif kind == "error":
                self.statusBar().showMessage("任务异常：" + event["message"])

    def worker_error(self, error):
        if error == QProcess.FailedToStart:
            self.event_timer.stop()
            self.set_busy(False)
            if self.batch_lock:
                self.batch_lock.unlock()
            self.close_after = False
            self.statusBar().showMessage("后台进程启动失败：" + self.process.errorString())

    def show_stage_progress(self, video_id, stage):
        for index, row in enumerate(self.rows):
            if row['video_id'] == video_id:
                self.table.item(index, 7).setText(stage + '…')
                break

    def show_task_position(self, event):
        total = event.get('task_total') or len(self.batch_task_ids)
        index = event.get('task_index')
        if index is None and event.get('video_id') in self.batch_task_ids:
            index = self.batch_task_ids.index(event['video_id']) + 1
        if total and index:
            self.work_status.setText(f'处理中 {index} / 共 {total}')
        else:
            self.work_status.setText('处理中 · 并发上限 1')

    def show_download_progress(self, event):
        self.current_id = event['video_id']
        self.current_stage = '下载视频 / 音轨'
        def size(value):
            return f'{value / 1048576:.1f} MB' if value >= 1048576 else f'{value / 1024:.0f} KB'
        received, total = event['received'], event['total']
        percent = event.get('percent')
        amount = size(received) + (' / ' + size(total) if total else ' / 总大小未知')
        speed = size(event['speed']) + '/s'
        elapsed = received / event['speed'] if event.get('speed') else 0
        self.download_bar.setRange(0, 1000 if percent is not None else 0)
        if percent is not None:
            self.download_bar.setValue(round(percent * 10))
            self.download_bar.setFormat(f'{percent:.1f}%')
        self.show_task_position(event)
        self.work_detail.setText(self.current_id + '\n' + self.current_stage)
        self.transfer_detail.setText(amount + f'\n平均速度 {speed} · 已用时 {elapsed:.1f} 秒')
        brief = f'下载 {percent:.1f}%' if percent is not None else '下载 ' + size(received)
        # Byte events update only the active row, not the entire candidate table.
        for index, row in enumerate(self.rows):
            if row['video_id'] == self.current_id:
                self.table.item(index, 5).setText(brief)
                self.table.item(index, 5).setToolTip(amount + ' · ' + speed)
        self.statusBar().showMessage(self.current_id + ' · ' + brief + ' · ' + amount + ' · ' + speed)

    def worker_finished(self, code, status):
        self.poll_events()
        self.event_timer.stop()
        self.current_id = ""
        self.batch_task_ids = []
        self.work_status.setText("就绪 · 并发上限 1")
        self.download_bar.setRange(0, 1000)
        self.download_bar.setValue(0)
        self.download_bar.setFormat('本轮已结束')
        self.transfer_detail.setText('结果已保存；可查看检测证据')
        self.refresh_table()
        self.set_busy(False)
        if self.batch_lock:
            self.batch_lock.unlock()
        if code:
            self.statusBar().showMessage("后台任务异常退出，进度已保留。可继续或检查 runtime 中的任务事件记录。")
        if self.close_after:
            self.close()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "task_side"):
            self.task_side.setVisible(self.width() >= 1250)
        if hasattr(self, "review"):
            self.review.splitter.setOrientation(Qt.Vertical if self.width() < 1150 else Qt.Horizontal)

    def closeEvent(self, event):
        if self.has_active_background_tasks():
            self.statusBar().showMessage('后台任务仍在运行，请等待完成后关闭。')
            event.ignore()
            return
        if self.is_running():
            if not self.close_after:
                answer = QMessageBox.question(self, "任务仍在运行", "等待当前素材完成，保存进度并退出？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if answer == QMessageBox.Yes:
                    self.close_after = True
                    self.pause()
            event.ignore()
            return
        self.review.player.stop()
        event.accept()


def configure_app(app):
    # Qt's offscreen platform may not discover Windows system fonts automatically.
    if "Microsoft YaHei" not in QFontDatabase.families():
        import os
        font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc"
        if font.is_file():
            QFontDatabase.addApplicationFont(str(font))
    app.setApplicationName("素材投放助手")
    app.setOrganizationName("Dianzhong")
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei", 10))
    app.setStyleSheet(STYLE)


def main():
    prepare_environment()
    app = QApplication(sys.argv[:1])
    configure_app(app)
    window = MainWindow()
    window.show()
    return app.exec()
