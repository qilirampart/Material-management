"""Clickable, isolated UI proposal. Never downloads, encodes, or uploads files."""
import argparse
import copy
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QStackedWidget, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QListWidget, QListWidgetItem, QFrame, QLineEdit, QComboBox, QCheckBox, QSpinBox,
    QDoubleSpinBox, QFormLayout, QDialog, QDialogButtonBox, QPlainTextEdit,
    QFileDialog, QTabWidget, QScrollArea, QProgressBar,
)
from src.variant_dialog import VariantDialog
from src.desktop import configure_app

STYLE = """
QWidget { font-family:'Microsoft YaHei'; font-size:13px; color:#193941; }
QWidget#shell { background:#F3F6F7; }
QLabel#heading { font-size:25px; font-weight:700; }
QLabel#section { font-size:17px; font-weight:600; }
QLabel#muted { color:#6D8187; }
QLabel#eyebrow { color:#0F766E; font-size:12px; font-weight:600; }
QLabel#badge { background:#E4EFEC; color:#0F766E; padding:5px 10px; border-radius:4px; }
QFrame#panel { background:white; border:1px solid #DCE5E7; border-radius:8px; }
QFrame#panel QLabel { background:transparent; }
QPushButton { background:white; border:1px solid #CCD8DC; border-radius:5px; padding:8px 12px; min-height:20px; }
QPushButton:hover { background:#ECF5F2; border-color:#7BAAA2; }
QPushButton:disabled { color:#99A5A8; background:#EDF1F2; border-color:#DEE5E7; }
QPushButton#primary { background:#0F766E; color:white; border-color:#0F766E; }
QPushButton#step { text-align:left; background:white; padding:12px; font-weight:500; }
QPushButton#step:checked { border:2px solid #0F766E; background:#EAF4F1; color:#0B645D; padding:11px; }
QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox,QPlainTextEdit { background:white; border:1px solid #CFDCDF; border-radius:4px; padding:7px; }
QTableWidget { background:white; alternate-background-color:#F8FBFA; border:0; gridline-color:#E9EFF0; selection-background-color:#E7F2EF; selection-color:#193941; }
QHeaderView::section { background:#F3F7F7; color:#5C737A; border:0; padding:10px 6px; font-weight:500; }
QTableWidget::indicator,QCheckBox::indicator,QListWidget::indicator { width:17px; height:17px; }
QListWidget { background:white; border:0; outline:0; }
QListWidget::item { padding:16px 8px; border-bottom:1px solid #EBF0F0; }
QListWidget::item:selected { background:#E5F1ED; color:#14574E; }
QTabWidget::pane { border:1px solid #DFE7E7; background:white; }
QTabBar::tab { background:#F1F5F5; padding:10px 16px; border:0; }
QTabBar::tab:selected { background:#E4F0EC; color:#0F766E; }
QProgressBar { border:0; background:#E7EEED; border-radius:3px; text-align:center; height:8px; }
QProgressBar::chunk { background:#0F766E; border-radius:3px; }
QScrollArea { border:0; background:transparent; }
"""


def label(text, kind='muted'):
    item = QLabel(text)
    item.setObjectName(kind)
    item.setWordWrap(True)
    if kind == 'badge':
        item.setWordWrap(False)
    return item


def button(text, callback, primary=False):
    item = QPushButton(text)
    if primary:
        item.setObjectName('primary')
    item.clicked.connect(callback)
    return item


def panel(heading=None):
    item = QFrame()
    item.setObjectName('panel')
    box = QVBoxLayout(item)
    box.setContentsMargins(16, 16, 16, 16)
    box.setSpacing(12)
    if heading:
        box.addWidget(label(heading, 'section'))
    return item, box


def table(headers):
    item = QTableWidget(0, len(headers))
    item.setHorizontalHeaderLabels(headers)
    item.verticalHeader().hide()
    item.verticalHeader().setDefaultSectionSize(43)
    item.setEditTriggers(QAbstractItemView.NoEditTriggers)
    item.setSelectionBehavior(QAbstractItemView.SelectRows)
    item.setSelectionMode(QAbstractItemView.SingleSelection)
    item.setAlternatingRowColors(True)
    item.setWordWrap(False)
    item.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    item.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
    item.setColumnWidth(0, 52)
    return item


def fill_table(widget, rows):
    widget.blockSignals(True)
    widget.setRowCount(len(rows))
    for r, values in enumerate(rows):
        check = QTableWidgetItem()
        check.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
        check.setCheckState(Qt.Checked if r == 0 else Qt.Unchecked)
        widget.setItem(r, 0, check)
        for c, value in enumerate(values, 1):
            cell = QTableWidgetItem(str(value))
            cell.setToolTip(str(value))
            if value in ('本地可用', '可上传', '已完成', '上传成功'):
                cell.setForeground(Qt.darkGreen)
            widget.setItem(r, c, cell)
    widget.blockSignals(False)


def checked_rows(widget):
    return [r for r in range(widget.rowCount()) if widget.item(r, 0).checkState() == Qt.Checked]


def selection_bar(widget):
    row = QHBoxLayout()
    count = label('')
    count.setWordWrap(False)
    def update():
        count.setText(f'已勾选 {len(checked_rows(widget))} 条 / 共 {widget.rowCount()} 条')
    def change(action):
        widget.blockSignals(True)
        for r in range(widget.rowCount()):
            cell = widget.item(r, 0)
            value = action == 'all' or (action == 'invert' and cell.checkState() != Qt.Checked)
            cell.setCheckState(Qt.Checked if value else Qt.Unchecked)
        widget.blockSignals(False)
        update()
    for name, action in [('全选', 'all'), ('反选', 'invert'), ('清除选择', 'clear')]:
        row.addWidget(button(name, lambda _, a=action: change(a)))
    row.addWidget(count)
    row.addStretch()
    widget.itemChanged.connect(lambda _: update())
    update()
    return row, update


def read_cases():
    paths = [
        ROOT / 'output/素材再创作/20261112_184221_9b63ef/recreation.json',
        ROOT / 'output/recreation-acceptance/素材再创作/20261112_153749_dafa1d/recreation.json',
    ]
    cases = []
    for path in paths:
        state = json.loads(path.read_text(encoding='utf-8'))
        drama = state['dramas'][0]
        cases.append({'id': drama['id'], 'name': drama['name'], 'sources': copy.deepcopy(state['sources']),
                      'folder': str(path.parent), 'queued': False})
    return cases


class ImportDialog(QDialog):
    def __init__(self, owner, module):
        super().__init__(owner)
        self.owner, self.module = owner, module
        self.setWindowTitle('导入视频 · ' + module)
        self.resize(930, 560)
        box = QVBoxLayout(self)
        box.setSpacing(12)
        box.addWidget(label('从下载批次导入', 'section'))
        row = QHBoxLayout()
        self.batch = QComboBox()
        for case in owner.cases:
            self.batch.addItem(case['id'] + ' · ' + case['name'])
        row.addWidget(self.batch, 1)
        row.addWidget(button('从本地导入…', self.local_import))
        box.addLayout(row)
        self.videos = table(['勾选', '素材', '下载状态'])
        self.videos.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        bar, self.update_count = selection_bar(self.videos)
        box.addLayout(bar)
        box.addWidget(self.videos, 1)
        self.note = label('未下载素材会先确认下载，完成后加入处理列表。')
        box.addWidget(self.note)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(button('取消', self.reject))
        actions.addWidget(button('导入勾选视频', self.import_selected, True))
        box.addLayout(actions)
        self.batch.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self.items = self.owner.cases[self.batch.currentIndex()]['sources']
        fill_table(self.videos, [(x['name'], '本地可用' if x.get('path') else '未下载') for x in self.items])
        self.update_count()

    def local_import(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '选择本地视频', '', '视频 (*.mp4 *.mov *.mkv *.avi)')
        if paths:
            self.owner.imported[self.module].extend({'name': Path(p).name, 'drama': '本地导入', 'path': p} for p in paths)
            self.owner.refresh_processing(self.module)
            self.accept()

    def import_selected(self):
        selected = [self.items[r] for r in checked_rows(self.videos)]
        if not selected:
            self.note.setText('请先勾选需要导入的素材。')
            return
        missing = [x for x in selected if not x.get('path')]
        if missing:
            confirm = QDialog(self)
            confirm.setWindowTitle('下载后导入')
            confirm.resize(470, 210)
            box = QVBoxLayout(confirm)
            box.setSpacing(16)
            box.addWidget(label(f'{len(missing)} 条素材尚未下载', 'section'))
            box.addWidget(label(f'先下载这 {len(missing)} 条，再加入“{self.module}”处理列表。'))
            box.addWidget(label('界面预览：此处只演示状态流转，不实际下载。'))
            actions = QHBoxLayout()
            actions.addStretch()
            actions.addWidget(button('返回选择', confirm.reject))
            actions.addWidget(button('同意下载并导入', confirm.accept, True))
            box.addLayout(actions)
            if confirm.exec() != QDialog.Accepted:
                return
            for item in missing:
                item['path'] = 'preview-only'
                item['preview_download'] = True
        existing = {x['name'] for x in self.owner.imported[self.module]}
        self.owner.imported[self.module].extend(copy.deepcopy(x) for x in selected if x['name'] not in existing)
        self.owner.refresh_processing(self.module)
        self.owner.refresh_downloads()
        self.owner.notify(f'预览：已将 {len(selected)} 条视频加入“{self.module}”列表')
        self.accept()


class WorkflowPreview(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName('shell')
        self.setWindowTitle('素材再创作 · 五步工作流 UI 预览')
        self.resize(1360, 860)
        self.setMinimumSize(1040, 680)
        self.cases = read_cases()
        first = next(x for x in self.cases[0]['sources'] if x.get('path'))
        self.imported = {'改 MD5': [copy.deepcopy(first)], '微创新': [copy.deepcopy(first)]}
        self.process_tables, self.process_counts, self.process_result_labels = {}, {}, {}
        self.products = []
        original = json.loads((Path(self.cases[1]['folder']) / 'recreation.json').read_text(encoding='utf-8'))
        for item in original['outputs']:
            self.products.append({'name': Path(item['path']).name, 'drama': item['drama'],
                                  'module': '改 MD5' if item['mode'] == 'md5' else '微创新', 'status': '可上传'})
        box = QVBoxLayout(self)
        box.setContentsMargins(24, 20, 24, 14)
        box.setSpacing(14)
        heading = QHBoxLayout()
        heading.addWidget(label('素材再创作', 'heading'))
        heading.addStretch()
        heading.addWidget(label('UI 预览 · 不执行真实下载或上传', 'badge'))
        box.addLayout(heading)
        box.addWidget(label('登录共用，批次独立。下载后任选改 MD5 或微创新，成品统一上传。'))
        nav = QHBoxLayout()
        nav.setSpacing(8)
        self.steps = []
        for i, name in enumerate(['登录点众智投', '视频下载', '改 MD5', '微创新', '自动上传']):
            step = button(f'{i+1:02d}   {name}', lambda _, p=i: self.go(p))
            step.setObjectName('step')
            step.setCheckable(True)
            step.setMinimumHeight(38)
            self.steps.append(step)
            nav.addWidget(step, 1)
        box.addLayout(nav)
        self.stack = QStackedWidget()
        box.addWidget(self.stack, 1)
        self.stack.addWidget(self.login_page())
        self.stack.addWidget(self.download_page())
        self.stack.addWidget(self.processing_page('改 MD5'))
        self.stack.addWidget(self.processing_page('微创新'))
        self.stack.addWidget(self.upload_page())
        self.message = label('预览已载入两个真实剧目的已采集信息。可切换页面和批次，体验导入与处理流转。')
        box.addWidget(self.message)
        self.go(1)

    def notify(self, text):
        self.message.setText(text)

    def go(self, page):
        self.stack.setCurrentIndex(page)
        for i, step in enumerate(self.steps):
            step.setChecked(i == page)

    def login_page(self):
        page, box = panel()
        row = QHBoxLayout()
        row.addWidget(label('点众智投', 'section'))
        row.addStretch()
        row.addWidget(label('正式版复用现有平台工作台与登录态', 'badge'))
        box.addLayout(row)
        toolbar = QHBoxLayout()
        for text in ['←', '→', '刷新']:
            toolbar.addWidget(button(text, lambda: self.notify('预览：正式接入后使用现有内置浏览器导航')))
        toolbar.addWidget(QLineEdit('https://market.wuread.cn/market-admin/'), 1)
        toolbar.addWidget(button('打开已登录 Edge', lambda: self.notify('预览：复用平台工作台的已有登录，不创建第二套登录')))
        toolbar.addWidget(button('新建登录', lambda: self.notify('预览：正式接入后在此扫码登录'), True))
        box.addLayout(toolbar)
        browser = QFrame()
        browser.setObjectName('browserPreview')
        browser.setStyleSheet('QFrame#browserPreview {background:#F8FAFA;border:1px solid #E0E8EA;}')
        content = QVBoxLayout(browser)
        content.addStretch()
        title = label('点众智投平台', 'heading')
        title.setAlignment(Qt.AlignCenter)
        content.addWidget(title)
        description = label('这里直接显示现有平台工作台的网页\n登录后，下载与上传共用这一会话。')
        description.setAlignment(Qt.AlignCenter)
        content.addWidget(description)
        content.addStretch()
        box.addWidget(browser, 1)
        footer = QHBoxLayout()
        footer.addWidget(label('本页只负责登录和网页操作，不混放素材处理控件。'))
        footer.addStretch()
        footer.addWidget(button('去视频下载 →', lambda: self.go(1), True))
        box.addLayout(footer)
        return page

    def download_page(self):
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        sidebar, left = panel('下载批次')
        sidebar.setFixedWidth(270)
        left.addWidget(button('+ 批量导入剧目 ID', self.add_batch, True))
        left.addWidget(button('导入批次文件…', self.import_batch_file))
        self.batch_list = QListWidget()
        self.batch_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for index, case in enumerate(self.cases):
            item = QListWidgetItem(self.batch_text(index))
            item.setToolTip(case['name'])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.batch_list.addItem(item)
        left.addWidget(self.batch_list, 1)
        left.addWidget(button('将勾选批次加入下载队列', self.queue_batches))
        self.queue_label = label('下载队列 0 个批次\n按批次排队，每部剧独立保存')
        left.addWidget(self.queue_label)
        row.addWidget(sidebar)
        main, box = panel()
        self.batch_heading = label('', 'section')
        box.addWidget(self.batch_heading)
        self.batch_description = label('')
        box.addWidget(self.batch_description)
        actions = QHBoxLayout()
        actions.addWidget(button('获取本批次素材', lambda: self.notify('预览：该批次已载入真实采集结果，正式版在此查询全部分页'), True))
        actions.addWidget(label('名称含 二创 / 精剪原片 · 自动翻页'))
        actions.addStretch()
        actions.addWidget(button('打开本批目录', lambda: self.notify(self.cases[self.batch_list.currentRow()]['folder'])))
        box.addLayout(actions)
        self.download_table = table(['勾选', '素材名称', '尺寸', '下载状态'])
        self.download_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.download_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        bar, self.update_download_count = selection_bar(self.download_table)
        box.addLayout(bar)
        box.addWidget(self.download_table, 1)
        self.download_progress = QProgressBar()
        self.download_progress.setRange(0, 100)
        self.download_progress.setValue(0)
        box.addWidget(self.download_progress)
        self.download_status = label('就绪 · 先勾选本批素材，再下载或导入处理模块')
        box.addWidget(self.download_status)
        footer = QHBoxLayout()
        footer.addWidget(button('下载本批勾选素材', self.download_selected, True))
        footer.addWidget(button('暂停队列', lambda: self.notify('预览：下载队列已暂停')))
        footer.addStretch()
        footer.addWidget(button('导入改 MD5 →', lambda: self.import_from_download('改 MD5')))
        footer.addWidget(button('导入微创新 →', lambda: self.import_from_download('微创新')))
        box.addLayout(footer)
        row.addWidget(main, 1)
        self.batch_list.currentRowChanged.connect(self.refresh_downloads)
        self.batch_list.setCurrentRow(0)
        return page

    def batch_text(self, index):
        case = self.cases[index]
        name = case['name']
        wrapped = name[:10] + ('\n' + name[10:] if len(name) > 10 else '')
        available = sum(bool(x.get('path')) for x in case['sources'])
        return f"批次 {index+1:02d}\n{wrapped}\n{case['id']}\n{len(case['sources'])} 条素材 · 本地可用 {available} 条"

    def refresh_downloads(self):
        i = self.batch_list.currentRow()
        if i < 0:
            return
        case = self.cases[i]
        self.batch_list.item(i).setText(self.batch_text(i))
        self.batch_heading.setText(case['name'])
        available = sum(bool(x.get('path')) for x in case['sources'])
        self.batch_description.setText(f"批次 {i+1:02d}   /   剧目 {case['id']}   /   共 {len(case['sources'])} 条，已下载 {available} 条")
        self.download_items = case['sources']
        values = []
        for x in self.download_items:
            meta = x.get('metadata') or {}
            dimensions = f"{meta['width']}×{meta['height']}" if meta.get('width') else '下载后读取'
            values.append((x['name'], dimensions, '本地可用' if x.get('path') else '待下载'))
        fill_table(self.download_table, values)
        self.update_download_count()

    def add_batch(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('批量导入剧目')
        dialog.resize(600, 380)
        box = QVBoxLayout(dialog)
        box.addWidget(label('每行一个剧目，自动建立独立批次', 'section'))
        input_ = QPlainTextEdit('41000447945-捍卫婚前财产，我替自己撑腰\n41000329324-垃圾桶里捡到爹')
        box.addWidget(input_)
        box.addWidget(label('同一轮导入可包含多个剧目；批次、下载进度和目录互不混用。'))
        controls = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        controls.button(QDialogButtonBox.Ok).setText('建立独立批次')
        controls.button(QDialogButtonBox.Cancel).setText('取消')
        controls.accepted.connect(dialog.accept)
        controls.rejected.connect(dialog.reject)
        box.addWidget(controls)
        if dialog.exec() == QDialog.Accepted:
            self.notify('预览：两个独立剧目批次已展示在左侧，可分别查看和加入队列')

    def import_batch_file(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '导入批次视频信息', '', '批次文件 (*.xlsx *.csv *.json)')
        if paths:
            self.notify(f'预览：已选择 {len(paths)} 个批次文件；正式接入后逐个解析并建立批次')

    def queue_batches(self):
        count = sum(self.batch_list.item(i).checkState() == Qt.Checked for i in range(self.batch_list.count()))
        self.queue_label.setText(f'下载队列 {count} 个批次\n按批次排队，每部剧独立保存')
        self.notify(f'预览：{count} 个批次已加入下载队列' if count else '请先勾选左侧需要排队的批次')

    def download_selected(self):
        selected = [self.download_items[r] for r in checked_rows(self.download_table)]
        if not selected:
            self.notify('请先勾选需要下载的素材')
            return
        for item in selected:
            if not item.get('path'):
                item.update(path='preview-only', preview_download=True)
        self.refresh_downloads()
        self.download_progress.setValue(100)
        self.download_status.setText(f'预览演示：本轮 {len(selected)} 条已下载，可导入改 MD5 或微创新')

    def import_from_download(self, module):
        selected = [self.download_items[r] for r in checked_rows(self.download_table)]
        if not selected:
            self.notify('请先勾选需要导入的素材')
            return
        self.go(2 if module == '改 MD5' else 3)
        dialog = ImportDialog(self, module)
        dialog.batch.setCurrentIndex(self.batch_list.currentRow())
        selected_ids = {x['video_id'] for x in selected}
        for i, item in enumerate(dialog.items):
            dialog.videos.item(i, 0).setCheckState(Qt.Checked if item['video_id'] in selected_ids else Qt.Unchecked)
        dialog.exec()

    def processing_page(self, module):
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        main, box = panel()
        heading = QHBoxLayout()
        heading.addWidget(label('视频列表', 'section'))
        heading.addStretch()
        heading.addWidget(button('+ 导入视频', lambda: ImportDialog(self, module).exec(), True))
        box.addLayout(heading)
        box.addWidget(label('从下载批次选择，或直接导入本地视频。'))
        videos = table(['勾选', '视频 / 来源批次', '信息', '状态'])
        videos.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        videos.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        bar, update = selection_bar(videos)
        self.process_tables[module], self.process_counts[module] = videos, update
        box.addLayout(bar)
        box.addWidget(videos, 1)
        result = label('处理完成的成品会出现在自动上传页。')
        self.process_result_labels[module] = result
        box.addWidget(result)
        actions = QHBoxLayout()
        actions.addWidget(button('移出列表', lambda: self.remove_inputs(module)))
        actions.addStretch()
        actions.addWidget(button('查看本模块成品 →', lambda: self.view_products(module)))
        box.addLayout(actions)
        row.addWidget(main, 3)
        settings, settings_box = panel('处理设置' if module == '改 MD5' else '微创新设置')
        settings.setMinimumWidth(390)
        settings.setMaximumWidth(470)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName('processingContent')
        content.setStyleSheet('QWidget#processingContent { background:white; }')
        right = QVBoxLayout(content)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(12)
        scroll.setWidget(content)
        settings_box.addWidget(scroll, 1)
        if module == '改 MD5':
            right.addWidget(label('仅改 MD5', 'eyebrow'))
            right.addWidget(label('保留原音画，不重新编码。生成独立副本，原文件不变。'))
        else:
            tabs = QTabWidget()
            tabs.setMinimumHeight(250)
            tabs.addTab(self.micro_picture(), '画面')
            tabs.addTab(self.micro_time(), '时长与速度')
            tabs.addTab(self.micro_text(), '文字与声音')
            right.addWidget(tabs, 1)
        form = QFormLayout()
        form.addRow('上传人缩写', QLineEdit('PSK'))
        number = QSpinBox()
        number.setRange(1, 10)
        form.addRow('每条生成', VariantDialog._stepper(number, '生成数量'))
        form.addRow('命名前缀', label('APP-繁花-王俨-' + ('改md5' if module == '改 MD5' else '微创新')))
        right.addLayout(form)
        if module == '改 MD5':
            preview, preview_box = panel('输出示例')
            preview_box.addWidget(label('APP-繁花-王俨-改md5-剧名-PSK-261112-01.mp4'))
            preview_box.addWidget(label('按来源批次与剧名保存；记录新旧 MD5。'))
            right.addWidget(preview)
            right.addStretch()
        else:
            right.addWidget(label('输出约束：720×1280 · 3500–5000 kbps · ≤510 MB'))
        settings_box.addWidget(button('生成一条样片' if module == '微创新' else '处理勾选视频',
                               lambda: self.process_demo(module), True))
        if module == '微创新':
            settings_box.addWidget(button('批量处理勾选视频', lambda: self.process_demo(module)))
        row.addWidget(settings, 2)
        self.refresh_processing(module)
        return page

    def micro_picture(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(self.checked_option('竖屏背景', True))
        background = QComboBox()
        background.addItems(['模糊背景 · 完整保留前景', '黑边背景'])
        box.addWidget(background)
        form = QFormLayout()
        form.addRow('输出尺寸', label('720 × 1280'))
        position = QComboBox()
        position.addItems(['居中', '居中偏上（拟新增）'])
        form.addRow('前景位置', position)
        box.addLayout(form)
        box.addWidget(self.checked_option('轻度调色', True))
        box.addWidget(label('亮度、对比度与饱和度轻微调整，多版本使用不同强度。'))
        box.addWidget(button('查看既有样片效果', self.show_sample))
        box.addStretch()
        return page

    def show_sample(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('既有微创新样片 · 非当前视频处理结果')
        box = QVBoxLayout(dialog)
        image = QLabel()
        picture = ROOT / 'output/recreation-acceptance/素材再创作/20261112_153749_dafa1d/micro-50.png'
        image.setPixmap(QPixmap(str(picture)).scaled(315, 560, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        box.addWidget(image)
        box.addWidget(button('关闭', dialog.accept))
        dialog.exec()

    @staticmethod
    def checked_option(text, checked=False):
        item = QCheckBox(text)
        item.setChecked(checked)
        return item

    def micro_time(self):
        page = QWidget()
        box = QVBoxLayout(page)
        form = QFormLayout()
        for name, value, suffix in [('去掉开头', .15, ' 秒'), ('去掉结尾', .15, ' 秒'), ('播放速度', 1.02, ' 倍')]:
            spin = QDoubleSpinBox()
            spin.setRange(.8 if suffix == ' 倍' else 0, 1.2 if suffix == ' 倍' else 60)
            spin.setSingleStep(.01)
            spin.setSuffix(suffix)
            spin.setValue(value)
            form.addRow(name, VariantDialog._stepper(spin, name))
        box.addLayout(form)
        box.addWidget(self.checked_option('保持音高', True))
        box.addWidget(label('剧情取舍由人工确认，模型接口后续接入。'))
        box.addStretch()
        return page

    def micro_text(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(label('顶部文字', 'section'))
        box.addWidget(QLineEdit('热门短剧'))
        box.addWidget(label('音频', 'section'))
        sound = QComboBox()
        sound.addItems(['保留原声', '背景音乐替换（后续）'])
        box.addWidget(sound)
        box.addWidget(label('保留对白；更换音乐需要单独选择音轨。'))
        box.addStretch()
        return page

    def refresh_processing(self, module):
        rows = []
        for item in self.imported[module]:
            meta = item.get('metadata') or {}
            info = f"{meta.get('duration', 0):.1f} 秒" if meta.get('duration') else '本地视频'
            rows.append((item['name'], info, '已完成' if item.get('preview_processed') else '待处理'))
        fill_table(self.process_tables[module], rows)
        self.process_counts[module]()

    def remove_inputs(self, module):
        selected = set(checked_rows(self.process_tables[module]))
        self.imported[module] = [x for i, x in enumerate(self.imported[module]) if i not in selected]
        self.refresh_processing(module)
        self.notify('已从当前模块移出，原视频与下载批次均保留')

    def process_demo(self, module):
        selected = [self.imported[module][r] for r in checked_rows(self.process_tables[module])]
        if not selected:
            self.notify('请先勾选视频')
            return
        for item in selected:
            item['preview_processed'] = True
            drama = item.get('drama', '本地导入')
            kind = '改md5' if module == '改 MD5' else '微创新'
            self.products.append({'name': f'APP-繁花-王俨-{kind}-{drama}-PSK-261112-01.mp4',
                                  'drama': drama, 'module': module, 'status': '预览成品'})
        self.process_result_labels[module].setText(f'预览演示：已生成 {len(selected)} 个成品，可前往自动上传页选择。')
        self.refresh_products()
        self.refresh_processing(module)
        self.notify('预览演示已完成，未创建或修改任何视频文件')

    def view_products(self, module):
        self.product_filter.setCurrentText(module)
        self.go(4)

    def upload_page(self):
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        main, box = panel('选择待上传成品')
        filters = QHBoxLayout()
        self.product_filter = QComboBox()
        self.product_filter.addItems(['全部处理来源', '改 MD5', '微创新'])
        self.product_filter.currentIndexChanged.connect(self.refresh_products)
        filters.addWidget(self.product_filter)
        filters.addWidget(label('只显示处理完成的视频，原片不混入此处。'))
        filters.addStretch()
        box.addLayout(filters)
        self.product_table = table(['勾选', '成品名称', '处理来源', '状态'])
        self.product_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.product_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        bar, self.update_product_count = selection_bar(self.product_table)
        box.addLayout(bar)
        box.addWidget(self.product_table, 1)
        box.addWidget(label('上传按剧目分组，每批最多 50 条；不同剧目不会填入同一个表单。'))
        row.addWidget(main, 3)
        settings, right = panel('上传设置')
        settings.setFixedWidth(340)
        right.addWidget(label('共用第 1 步的点众智投登录', 'badge'))
        form = QFormLayout()
        form.addRow('编导', QLineEdit('白佳丽'))
        form.addRow('上传人缩写', QLineEdit('PSK'))
        form.addRow('建议短剧', label('按成品所属剧目自动填写'))
        form.addRow('可见范围', label('客户端二组'))
        right.addLayout(form)
        self.upload_stop = self.checked_option('上传完成后停在最终提交前', True)
        self.upload_stop.setEnabled(False)
        right.addWidget(self.upload_stop)
        right.addWidget(label('逐批填表、选择文件、执行上传；保留每个文件的成功与失败状态。'))
        right.addStretch()
        self.upload_result = label('待开始 · 没有正在上传的文件')
        right.addWidget(self.upload_result)
        right.addWidget(button('开始上传勾选成品', self.upload_demo, True))
        right.addWidget(button('返回智投页面查看', lambda: self.go(0)))
        row.addWidget(settings)
        self.refresh_products()
        return page

    def refresh_products(self):
        mode = self.product_filter.currentText()
        self.visible_products = [x for x in self.products if mode == '全部处理来源' or x['module'] == mode]
        fill_table(self.product_table, [(x['name'], x['module'], x['status']) for x in self.visible_products])
        self.update_product_count()

    def upload_demo(self):
        selected = checked_rows(self.product_table)
        if not selected:
            self.notify('请先勾选处理完成的成品')
            return
        self.upload_result.setText(f'预览：{len(selected)} 个文件上传完成\n停在最终提交前，等待人工确认。')
        self.notify('上传流程演示结束：未调用平台上传接口，未提交任何素材')


def verify(window):
    assert len(window.cases) == 2
    assert [len(x['sources']) for x in window.cases] == [171, 582]
    window.batch_list.setCurrentRow(1)
    assert window.download_table.rowCount() == 582
    window.batch_list.setCurrentRow(0)
    assert window.download_table.rowCount() == 171
    dialog = ImportDialog(window, '改 MD5')
    dialog.videos.item(1, 0).setCheckState(Qt.Checked)
    assert len(checked_rows(dialog.videos)) == 2
    previous = len(window.imported['改 MD5'])
    def approve_download():
        modal = QApplication.activeModalWidget()
        assert modal.windowTitle() == '下载后导入'
        next(b for b in modal.findChildren(QPushButton) if b.text() == '同意下载并导入').click()
    QTimer.singleShot(0, approve_download)
    dialog.import_selected()
    assert len(window.imported['改 MD5']) == previous + 1
    assert window.imported['改 MD5'][-1]['path'] == 'preview-only'
    dialog.close()
    before = len(window.products)
    window.process_demo('改 MD5')
    assert len(window.products) == before + 1
    window.product_filter.setCurrentText('改 MD5')
    assert all(x['module'] == '改 MD5' for x in window.visible_products)
    window.upload_demo()
    assert '最终提交前' in window.upload_result.text()
    print('Preview navigation, two independent batches, product routing and upload-stop state: OK')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--render', action='store_true')
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    if args.render or args.verify:
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    app = QApplication([])
    configure_app(app)
    app.setStyleSheet(STYLE)
    window = WorkflowPreview()
    if not args.render:
        available = app.primaryScreen().availableGeometry()
        window.resize(min(1360, available.width()-60), min(860, available.height()-60))
    window.show()
    if args.verify:
        verify(window)
        if args.render:
            window.close()
            window = WorkflowPreview()
            window.show()
    if args.render:
        root = ROOT / 'tmp/workflow-preview'
        root.mkdir(parents=True, exist_ok=True)
        for i, name in enumerate(['01-login', '02-download', '03-md5', '04-micro', '05-upload']):
            window.go(i)
            app.processEvents()
            window.grab().save(str(root / (name + '.png')))
        dialog = ImportDialog(window, '微创新')
        dialog.show()
        app.processEvents()
        dialog.grab().save(str(root / '06-import.png'))
        dialog.videos.item(1, 0).setCheckState(Qt.Checked)
        def capture_confirmation():
            modal = QApplication.activeModalWidget()
            modal.grab().save(str(root / '07-download-confirmation.png'))
            modal.reject()
        QTimer.singleShot(0, capture_confirmation)
        dialog.import_selected()
        dialog.close()
        window.resize(1040, 720)
        window.go(3)
        app.processEvents()
        window.grab().save(str(root / '08-compact-micro.png'))
        print('Compact preview size:', window.width(), window.height())
    if args.render or args.verify:
        window.close()
        return
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
