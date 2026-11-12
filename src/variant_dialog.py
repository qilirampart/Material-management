"""Native material-processing dialog; work stays off the Qt event thread."""
import threading
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QComboBox,
    QDoubleSpinBox, QSpinBox, QLineEdit, QCheckBox, QPlainTextEdit,
    QProgressBar, QScrollArea, QWidget, QAbstractSpinBox,
)
from src.ui_design import Background, btn, label
from src.desktop_widgets import local_open
from src.material_variants import VariantOptions, generate_variants


class VariantDialog(QDialog):
    result_ready = Signal(object)
    def __init__(self, items, output_root, parent=None):
        super().__init__(parent)
        self.items = items
        self.output_root = Path(output_root)
        self.task = None
        self.stop_event = threading.Event()
        self.outputs = []
        self.preview_path = None
        self.close_requested = False
        self.setWindowTitle('素材再加工')
        self.resize(780, 760)
        outer = QVBoxLayout(self)
        outer.addWidget(label('素材再加工', 'heading'))
        outer.addWidget(label(f'已选 {len(items)} 条本地视频 · 原文件保留，结果按剧名归档'))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        box = QVBoxLayout(content)
        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItem('微创新：竖屏背景与视频处理', 'micro')
        self.mode.addItem('仅改 MD5：保留音画，不重新编码', 'md5')
        form.addRow('处理方式', self.mode)
        self.uploader = QLineEdit()
        self.uploader.setPlaceholderText('用于输出文件名，例如 PSK')
        form.addRow('上传人缩写', self.uploader)
        self.count = QSpinBox()
        self.count.setRange(1, 10)
        self.count_field = self._stepper(self.count, '每条生成数量')
        form.addRow('每条生成数量', self.count_field)
        box.addLayout(form)
        self.processing_group = QGroupBox('微创新参数')
        fields = QFormLayout(self.processing_group)
        self.background = QComboBox()
        self.background.addItem('模糊背景 · 完整保留前景', 'blur')
        self.background.addItem('黑边背景 · 完整保留前景', 'black')
        fields.addRow('竖屏 720 × 1280', self.background)
        self.trim_start = self._decimal(0, 60, 0.15, ' 秒')
        self.trim_end = self._decimal(0, 60, 0.15, ' 秒')
        self.speed = self._decimal(0.8, 1.2, 1.02, ' 倍')
        fields.addRow('去掉开头', self._stepper(self.trim_start, '去掉开头'))
        fields.addRow('去掉结尾', self._stepper(self.trim_end, '去掉结尾'))
        fields.addRow('播放速度（保持音高）', self._stepper(self.speed, '播放速度'))
        self.color = QCheckBox('轻度调色；多个版本使用不同强度')
        self.color.setChecked(True)
        fields.addRow('画面风格', self.color)
        self.title = QLineEdit()
        self.title.setMaxLength(40)
        self.title.setPlaceholderText('可选，一行标题或角标文案')
        fields.addRow('顶部文字', self.title)
        box.addWidget(self.processing_group)
        box.addWidget(label('不自动判断精彩剧情；请先看样片，确认字幕、对白和时长。'
                            '仅改 MD5 不改变画面，也不保证平台认定为新素材。'))
        box.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        self.status = label('准备就绪 · 可先生成第一条的样片')
        outer.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        outer.addWidget(self.bar)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.log.setMaximumHeight(110)
        outer.addWidget(self.log)
        actions = QHBoxLayout()
        self.sample_button = btn('先生成一条样片', lambda: self.start(sample=True))
        self.preview_button = btn('播放最近成品', self.play_output)
        self.preview_button.setEnabled(False)
        self.start_button = btn('批量生成', self.start, True)
        self.stop_button = btn('停止处理', self.stop)
        self.stop_button.setEnabled(False)
        for control in (self.sample_button, self.preview_button, self.start_button, self.stop_button):
            actions.addWidget(control)
        outer.addLayout(actions)
        footer = QHBoxLayout()
        footer.addWidget(btn('打开输出目录', lambda: local_open(self.output_root)))
        footer.addStretch()
        self.import_button = btn('将成品加入候选区', self.accept, True)
        self.import_button.setEnabled(False)
        footer.addWidget(self.import_button)
        footer.addWidget(btn('关闭', self.reject))
        outer.addLayout(footer)
        self.mode.currentIndexChanged.connect(self.update_mode)

    @staticmethod
    def _stepper(spin, name):
        spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        spin.setAccessibleName(name)
        field = QWidget()
        row = QHBoxLayout(field)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        row.addWidget(spin, 1)
        for text, action, callback in (('−', '减少', spin.stepDown), ('+', '增加', spin.stepUp)):
            def step(checked=False, change=callback):
                change()
                spin.lineEdit().deselect()
            control = btn(text, step)
            control.setFixedWidth(36)
            control.setAccessibleName(action + name)
            control.setToolTip(action + name)
            row.addWidget(control)
        return field

    @staticmethod
    def _decimal(minimum, maximum, value, suffix):
        widget = QDoubleSpinBox()
        widget.setRange(minimum, maximum)
        widget.setDecimals(2)
        widget.setSingleStep(0.01)
        widget.setValue(value)
        widget.setSuffix(suffix)
        return widget

    def options(self, sample=False):
        return VariantOptions(
            mode=self.mode.currentData(), variants=1 if sample else self.count.value(),
            uploader=self.uploader.text().strip(), background=self.background.currentData(),
            trim_start=self.trim_start.value(), trim_end=self.trim_end.value(),
            speed=self.speed.value(), color_adjust=self.color.isChecked(), title=self.title.text().strip(),
        ).validate()

    def update_mode(self):
        self.processing_group.setEnabled(self.mode.currentData() == 'micro')

    def start(self, checked=False, *, sample=False):
        if self.task and self.task.isRunning():
            return
        try:
            options = self.options(sample)
            if not options.uploader:
                raise ValueError('请填写上传人缩写')
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.stop_event.clear()
        self.close_requested = False
        items = self.items[:1] if sample else self.items
        task = Background(lambda: generate_variants(
            items, self.output_root, options, progress=task.progress.emit,
            should_stop=self.stop_event.is_set,
        ), self)
        self.task = task
        task.progress.connect(self.show_progress)
        task.result.connect(self.show_result)
        task.failed.connect(self.status.setText)
        task.finished.connect(self.finished_processing)
        for control in (self.mode, self.count_field, self.uploader, self.processing_group,
                        self.start_button, self.sample_button, self.import_button):
            control.setEnabled(False)
        self.bar.setRange(0, 0)
        self.status.setText('正在准备样片…' if sample else '正在准备批量处理…')
        self.stop_button.setEnabled(True)
        task.start()

    def show_progress(self, event):
        phases = {'started': '读取视频', 'encoding': '转码中', 'validating': '校验音画',
                  'completed': '完成', 'failed': '失败'}
        self.status.setText(f"{event['index']} / {event['total']} · {event['video_id']} · "
                            + phases.get(event['phase'], event['phase']))
        self.bar.setRange(0, event['total'])
        self.bar.setValue(event['index'] if event['phase'] in {'completed', 'failed'} else event['index'] - 1)
        if event['phase'] in {'completed', 'failed'}:
            self.log.appendPlainText(self.status.text() + ('\n' + event['error'] if event.get('error') else ''))

    def show_result(self, result):
        self.outputs.extend(result['outputs'])
        self.result_ready.emit(result)
        if result['outputs']:
            self.preview_path = result['outputs'][-1]['path']
            self.preview_button.setEnabled(True)
        self.status.setText(f"本轮完成 {len(result['outputs'])} 个，失败 {len(result['failed'])} 个"
                            + ('；已停止' if result['stopped'] else '；请预览成品'))
        self.log.appendPlainText('处理记录：' + result['manifest'])

    def finished_processing(self):
        for control in (self.mode, self.count_field, self.uploader, self.start_button, self.sample_button):
            control.setEnabled(True)
        self.update_mode()
        self.stop_button.setEnabled(False)
        self.import_button.setEnabled(bool(self.outputs))
        if self.close_requested:
            super().reject()

    def play_output(self):
        if self.preview_path:
            local_open(self.preview_path)

    def stop(self):
        self.stop_event.set()
        self.stop_button.setEnabled(False)
        self.status.setText('正在停止当前处理，已完成的成品和记录会保留…')

    def reject(self):
        if self.task and self.task.isRunning():
            self.close_requested = True
            self.stop()
        else:
            super().reject()

    def closeEvent(self, event):
        if self.task and self.task.isRunning():
            self.close_requested = True
            self.stop()
            event.ignore()
        else:
            event.accept()
