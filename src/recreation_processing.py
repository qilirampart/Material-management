"""Independent MD5/micro workbenches using the existing video pipeline."""
import threading
import tempfile
from collections import defaultdict
from pathlib import Path
from dataclasses import asdict
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QFormLayout, QLineEdit,
    QSpinBox, QScrollArea,QComboBox,
    QProgressBar, QTableWidgetItem)
from src.ui_design import card, label, btn, Background
from src.desktop_widgets import local_open
from src.variant_dialog import VariantDialog
from src.material_variants import VariantOptions, generate_variants, render_micro_preview
from src.micro_preview import MicroPreviewDialog
from src.media import FFmpegCancelled, FFmpegError
from src.recreation import RecreationBatch
from src.micro_settings import MicroSettings


class ProcessingWorkbench(QWidget):
    finished = Signal()

    def __init__(self, owner, mode):
        super().__init__()
        self.owner, self.mode = owner, mode
        self.task, self.busy = None, False
        self.stop_event = threading.Event()
        self.items, self.last_output = [], ''
        self.preview_cache, self.preview_dialog = None, None
        self.preview_plan = None
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        main, box = card('视频列表')
        self.import_button = btn('+ 导入视频', lambda: owner.open_processing_import(mode), True)
        box.addWidget(self.import_button)
        self.table = owner._table(['勾选', '视频', '来源批次 / 剧目', '状态'])
        box.addLayout(owner._selection_bar(self.table))
        box.addWidget(self.table, 1)
        self.status = label('从下载批次选择，或直接导入本地视频。')
        box.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        box.addWidget(self.bar)
        actions = QHBoxLayout()
        self.remove_button = btn('移出列表', self.remove_selected)
        actions.addWidget(self.remove_button)
        self.preview_button = btn('播放最近成品', lambda: local_open(self.last_output))
        self.preview_button.setEnabled(False)
        actions.addWidget(self.preview_button)
        if mode=='micro':
            self.last_cover=''
            self.cover_button=btn('查看最近封面',lambda:local_open(self.last_cover))
            self.cover_button.setEnabled(False);actions.addWidget(self.cover_button)
        actions.addStretch()
        actions.addWidget(btn('查看本模块成品 →', lambda: owner.view_products(mode)))
        box.addLayout(actions)
        row.addWidget(main, 3)
        settings, right = card('仅改 MD5' if mode == 'md5' else '微创新设置')
        settings.setMinimumWidth(350)
        settings.setMaximumWidth(440)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.options_widget = QWidget()
        self.options_widget.setObjectName('processingOptions')
        self.options_widget.setStyleSheet('QWidget#processingOptions { background:white; }')
        fields = QVBoxLayout(self.options_widget)
        fields.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self.options_widget)
        right.addWidget(scroll, 1)
        if mode == 'micro':
            self.micro_settings = MicroSettings(presets_path=Path(owner.preferences_path).parent / 'micro-presets.json',
                region_source_provider=self.region_source)
            fields.addWidget(self.micro_settings)
            for name in ('background','trim_start','trim_end','speed','color','title'):
                setattr(self,name,getattr(self.micro_settings,name,None) or self.micro_settings.fields.get(name))
        else:
            fields.addWidget(label('保留原音画，不重新编码。生成独立副本，原视频不变。'))
        form = QFormLayout()
        self.uploader = QLineEdit()
        self.uploader.setPlaceholderText('例如 PSK')
        self.count = QSpinBox()
        self.count.setRange(1, 10)
        form.addRow('上传人缩写', self.uploader)
        form.addRow('每条生成', VariantDialog._stepper(self.count, '每条生成数量'))
        form.addRow('命名前缀', label('APP-繁花-王俨-' + ('改md5' if mode == 'md5' else '微创新')))
        fields.addLayout(form)
        fields.addWidget(label('按来源批次与剧名归档；成品自动进入上传页。'))
        if mode == 'micro':
            fields.addWidget(label('输出尺寸按画面设置 · 视频 >3500 且 ≤5000 kbps · 文件 ≤510 MB'))
        fields.addStretch()
        self.sample_button = btn('生成一条样片', lambda: self.start(sample=True))
        self.effect_button = btn('预览当前效果', lambda: self.start(preview=True))
        self.effect_button.setToolTip('预览第一条勾选视频，默认 10 秒；起点与时长可在参数区底部调整。不加入成品库。')
        if mode == 'micro':
            preview_actions=QHBoxLayout()
            self.preview_section=QComboBox()
            for text,value in [('主体效果','body'),('片头转场','head'),('片尾转场','tail')]:
                self.preview_section.addItem(text,value)
            self.preview_section.setToolTip('转场预览另含完整片头或片尾；下方时长是主体片段长度。')
            preview_form = QFormLayout()
            self.preview_start = VariantDialog._decimal(0, 86400, 0, ' 秒')
            self.preview_length = QSpinBox()
            self.preview_length.setRange(1, 30)
            self.preview_length.setValue(10)
            self.preview_length.setSuffix(' 秒')
            preview_form.addRow('原片预览起点', VariantDialog._stepper(self.preview_start, '原片预览起点'))
            preview_form.addRow('主体预览时长', VariantDialog._stepper(self.preview_length, '预览时长'))
            self.preview_section.currentIndexChanged.connect(lambda:self.preview_start.parentWidget().setEnabled(
                self.preview_section.currentData()=='body'))
            fields.insertLayout(fields.count()-1, preview_form)
            preview_actions.addWidget(self.preview_section,1);preview_actions.addWidget(self.effect_button,2)
            right.addLayout(preview_actions)
            right.addWidget(self.sample_button)
            self.sample_button.setText('生成完整样片（进入成品库）')
        self.start_button = btn('处理勾选视频' if mode == 'md5' else '批量处理勾选视频', self.start, True)
        right.addWidget(self.start_button)
        self.stop_button = btn('停止处理', self.stop)
        self.stop_button.setEnabled(False)
        right.addWidget(self.stop_button)
        row.addWidget(settings, 2)

    def refresh(self):
        try:
            self.items = self.owner.workspace.resolve_inputs(self.mode)
        except (OSError, ValueError, StopIteration) as exc:
            self.status.setText('来源记录不可用，请重新导入：' + str(exc))
            return
        checked = self.owner._checked_identities(self.table)
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.items))
        completed = {}
        for row, item in enumerate(self.items):
            identity = item['batch_folder'] + '|' + item['video_id']
            self.table.setItem(row, 0, self.owner._check_item(identity, checked))
            available = bool(item.get('path')) and Path(item['path']).is_file()
            status = '待处理' if available else '文件缺失，请重新下载'
            folder = item['batch_folder']
            if folder not in completed:
                batch = RecreationBatch.load(folder, recover_interrupted=False)
                completed[folder] = {x.get('source_video_id') for x in batch.state['outputs']
                                     if x.get('mode') == self.mode and Path(x['path']).is_file()}
            if available and item['video_id'] in completed[folder]:
                status = '已完成（可再次生成）'
            for col, value in enumerate((item['name'], Path(item['batch_folder']).name + ' · ' + item['drama'], status), 1):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                self.table.setItem(row, col, cell)
        self.table.blockSignals(False)
        self.owner._update_checked_count(self.table)

    def options(self, sample):
        values = self.micro_settings.values() if self.mode == 'micro' else {}
        return VariantOptions(mode=self.mode, uploader=self.uploader.text().strip(),
            variants=1 if sample else self.count.value(), **values).validate()

    def region_source(self):
        rows=self.owner.checked_rows(self.table)
        index=rows[0] if rows else max(0,self.table.currentRow())
        if index>=len(self.items) or not self.items[index].get('path') or not Path(self.items[index]['path']).is_file():
            raise ValueError('请先导入一条本地可用视频，再打开原片框选')
        return self.items[index]['path']

    def start(self, checked=False, *, sample=False, preview=False):
        if self.owner.work_in_progress():
            self.status.setText('请先完成当前任务')
            return
        items = [self.items[i] for i in self.owner.checked_rows(self.table)]
        try:
            options = self.options(sample or preview)
            if not preview and not options.uploader:
                raise ValueError('请填写上传人缩写')
            if not items or any(not x.get('path') or not Path(x['path']).is_file() for x in items):
                raise ValueError('请勾选本地可用的视频；缺失文件需重新下载')
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        if sample or preview:
            items = items[:1]
        frozen_plans={}
        if self.preview_plan and not preview and self.mode=='micro':
            def effects(values):
                return {k:v for k,v in values.items() if k not in {'uploader','variants'}}
            if effects(asdict(options))==effects(self.preview_plan['requested_options']):
                frozen_plans[(self.preview_plan['source_path'],1)]=VariantOptions(**self.preview_plan['resolved_options'])
        if preview:
            if self.preview_dialog:
                self.preview_dialog.done(0)
                self.preview_dialog.deleteLater()
                self.preview_dialog=None
            if self.preview_cache:
                self.preview_cache.cleanup()
            self.preview_cache = tempfile.TemporaryDirectory(prefix='dz-effect-preview-')
            preview_target = Path(self.preview_cache.name) / 'preview.mp4'
            preview_start, preview_seconds = self.preview_start.value(), self.preview_length.value()
            preview_section=self.preview_section.currentData()
        self.stop_event.clear()
        task = None
        def execute():
            if preview:
                try:
                    result = render_micro_preview(items[0]['path'], preview_target, options,
                        start=preview_start, seconds=preview_seconds, should_stop=self.stop_event.is_set,
                        text_context=items[0],
                        preview_section=preview_section,
                        progress=lambda phase: task.progress.emit({'phase': phase, 'index': 1,
                            'total': 1, 'video_id': '效果预览'}))
                except FFmpegCancelled:
                    return {'preview_error': '已停止预览；原片及设置保留。'}
                except (ValueError, FFmpegError) as exc:
                    return {'preview_error': '预览失败：' + str(exc)[-600:]}
                return {'preview': result}
            groups = defaultdict(list)
            for item in items:
                groups[item['batch_folder']].append(item)
            outputs, failed = [], []
            for folder, sources in groups.items():
                if self.stop_event.is_set():
                    break
                result = generate_variants(sources, Path(folder) / '加工成品', options,
                    progress=task.progress.emit, should_stop=self.stop_event.is_set,resolved_plans=frozen_plans)
                batch = RecreationBatch.load(folder, recover_interrupted=False)
                batch.add_outputs(result['outputs'])
                outputs.extend(result['outputs'])
                failed.extend(result['failed'])
            return {'outputs': outputs, 'failed': failed, 'stopped': self.stop_event.is_set()}
        task = Background(execute, self)
        self.task, self.busy = task, True
        task.progress.connect(self.show_progress)
        task.result.connect(self.show_result)
        task.failed.connect(self.status.setText)
        task.finished.connect(self.finish)
        for control in (self.table, self.options_widget, self.start_button, self.sample_button,
                        self.effect_button, self.import_button, self.remove_button):
            control.setEnabled(False)
        if self.mode=='micro':self.preview_section.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.bar.setRange(0, 0)
        task.start()

    def show_progress(self, event):
        self.status.setText(f"{event['index']} / {event['total']} · {event['video_id']} · "
                            + {'started': '读取视频', 'encoding': '转码中', 'validating': '校验中',
                               'completed': '完成', 'failed': '失败'}.get(event['phase'], event['phase']))

    def show_result(self, result):
        if 'preview_error' in result:
            self.status.setText(result['preview_error'])
            return
        if 'preview' in result:
            self.preview_plan=result['preview']
            self.status.setText('效果预览已生成；未加入成品库，可继续调整或批量生成。')
            self.preview_dialog = MicroPreviewDialog(result['preview'], self)
            cache = self.preview_cache
            self.preview_dialog.finished.connect(lambda: cache.cleanup())
            self.preview_dialog.setModal(True)
            self.preview_dialog.show()
            self.preview_dialog.player.play()
            return
        self.status.setText(f"完成 {len(result['outputs'])} 个 · 失败 {len(result['failed'])} 个"
                            + (' · 已停止' if result['stopped'] else ' · 已保存到来源批次'))
        if result['outputs']:
            self.last_output = result['outputs'][-1]['path']
            self.preview_button.setEnabled(True)
            if self.mode=='micro':
                self.last_cover=result['outputs'][-1].get('metadata',{}).get('cover',{}).get('path','')
                self.cover_button.setEnabled(bool(self.last_cover) and Path(self.last_cover).is_file())
        self.owner.refresh_outputs()

    def finish(self):
        self.busy = False
        for control in (self.table, self.options_widget, self.start_button, self.sample_button,
                        self.effect_button, self.import_button, self.remove_button):
            control.setEnabled(True)
        if self.mode=='micro':self.preview_section.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.refresh()
        self.finished.emit()

    def stop(self):
        self.stop_event.set()
        self.stop_button.setEnabled(False)
        self.status.setText('正在停止，已完成成品保留…')

    def remove_selected(self):
        if self.owner.work_in_progress():
            return
        remove = set(self.owner.checked_rows(self.table))
        self.owner.workspace.inputs[self.mode] = [x for i, x in enumerate(self.owner.workspace.inputs[self.mode]) if i not in remove]
        try:
            self.owner.workspace.save()
            self.refresh()
        except OSError:
            self.status.setText('未能保存列表，请检查目录权限')
