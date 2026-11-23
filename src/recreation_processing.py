"""Independent MD5/micro workbenches using the existing video pipeline."""
import threading
import tempfile
from collections import defaultdict
from pathlib import Path
from dataclasses import asdict
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QFormLayout, QLineEdit,
    QSpinBox, QScrollArea,QComboBox, QDialog, QPlainTextEdit, QDialogButtonBox,
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
        self.failures = []
        self.retry_options = None
        self.retry_plans = {}
        self.last_stop_reason = ''
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
        self.failure_button = btn('失败明细…', self.show_failures)
        self.retry_button = btn('仅重试失败项', lambda: self.start(retry=True))
        self.failure_button.setEnabled(False)
        self.retry_button.setEnabled(False)
        actions.addWidget(self.failure_button)
        actions.addWidget(self.retry_button)
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
        if self.last_output and not Path(self.last_output).is_file():
            self.last_output = ''
            self.preview_button.setEnabled(False)
        if self.mode == 'micro' and self.last_cover and not Path(self.last_cover).is_file():
            self.last_cover = ''
            self.cover_button.setEnabled(False)
        try:
            self.items = self.owner.workspace.resolve_inputs(self.mode)
        except (OSError, ValueError, StopIteration) as exc:
            self.status.setText('来源记录不可用，请重新导入：' + str(exc))
            return
        checked = self.owner._checked_identities(self.table)
        self.table.blockSignals(True)
        try:
            self._refresh_rows(checked)
        finally:
            self.table.blockSignals(False)
        self.owner._update_checked_count(self.table)
        issues = self.owner.workspace.input_issues[self.mode]
        if issues:
            self.status.setText(f'可显示 {len(self.items)} 条；跳过 {len(issues)} 条失效来源，不影响其他视频。')
        elif self.status.text().startswith(('可显示 ', '来源记录不可用')):
            self.status.setText(f'已载入 {len(self.items)} 条；缺失视频可重新下载或移出列表。')

    def _refresh_rows(self, checked):
        self.table.setRowCount(len(self.items))
        completed = {}
        recent_failures = defaultdict(list)
        for entry in self.failures:
            recent_failures[self.failure_key(entry)[:2]].append(entry)
        for row, item in enumerate(self.items):
            identity = item['batch_folder'] + '|' + item['video_id']
            self.table.setItem(row, 0, self.owner._check_item(identity, checked))
            available = bool(item.get('path')) and Path(item['path']).is_file()
            status = '待处理' if available else '文件缺失，请重新下载'
            folder = item['batch_folder']
            if folder not in completed:
                try:
                    batch = RecreationBatch.load(folder, recover_interrupted=False)
                    completed[folder] = {x.get('source_video_id') for x in batch.state['outputs']
                                         if x.get('mode') == self.mode and Path(x['path']).is_file()}
                except (OSError, ValueError):
                    completed[folder] = set()
                    status = '批次记录已变化，请刷新后重试'
            if available and item['video_id'] in completed[folder]:
                status = '已完成（可再次生成）'
            failures = recent_failures[(folder, item['video_id'])]
            if failures:
                if any(not entry['retryable'] for entry in failures):
                    status = '需要核对 · 查看明细'
                else:
                    status = f"{len(failures)} 版失败 · {failures[0]['stage']}"
            for col, value in enumerate((item['name'], Path(item['batch_folder']).name + ' · ' + item['drama'], status), 1):
                cell = QTableWidgetItem(value)
                cell.setToolTip('\n'.join(f"第 {entry['version']} 版：{entry['error']}" for entry in failures)
                                 if col == 3 and failures else value)
                self.table.setItem(row, col, cell)

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

    @staticmethod
    def failure_key(entry):
        return (entry['batch_folder'], entry['video_id'], entry.get('version'))

    def show_failures(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('本轮加工明细')
        dialog.resize(760, 460)
        layout = QVBoxLayout(dialog)
        details = QPlainTextEdit()
        details.setReadOnly(True)
        lines = []
        if self.last_stop_reason:
            lines.append(f'停止原因：{self.last_stop_reason}\n')
        for entry in self.failures:
            version = f" · 第 {entry['version']} 版" if entry.get('version') else ''
            retry = '可重试' if entry['retryable'] else '需先检查或恢复记录'
            lines.append(f"{entry['name']}{version} · {entry['stage']} · {retry}\n"
                         f"{Path(entry['batch_folder']).name}\n{entry['error']}")
            if entry.get('manifest'):
                lines.append(f"加工记录：{entry['manifest']}")
            lines.append('')
        details.setPlainText('\n'.join(lines))
        layout.addWidget(details)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText('关闭')
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
        dialog.deleteLater()

    def start(self, checked=False, *, sample=False, preview=False, retry=False):
        if self.owner.work_in_progress():
            self.status.setText('请先完成当前任务')
            return
        retry_versions = defaultdict(lambda: defaultdict(list))
        if retry:
            for entry in self.failures:
                if entry['retryable']:
                    retry_versions[entry['batch_folder']][entry['video_id']].append(entry['version'])
            items = [item for item in self.items if item['video_id'] in retry_versions.get(item['batch_folder'], {})]
        else:
            items = [self.items[i] for i in self.owner.checked_rows(self.table)]
        try:
            options = self.retry_options if retry else self.options(sample or preview)
            if retry and (not options or not items):
                raise ValueError('没有可重试的失败项；请确认原片仍在处理列表')
            if not preview and not options.uploader:
                raise ValueError('请填写上传人缩写')
            if not items or ((sample or preview) and not Path(items[0].get('path') or '.').is_file()):
                raise ValueError('请勾选本地可用的视频；缺失文件需重新下载')
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        if sample or preview:
            items = items[:1]
        frozen_plans={}
        if retry:
            frozen_plans = dict(self.retry_plans)
        elif self.preview_plan and not preview and self.mode=='micro':
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
        if not preview and not retry:
            self.retry_options, self.retry_plans = options, frozen_plans
            self.failures, self.last_stop_reason = [], ''
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
            outputs, failed, completed = [], [], set()
            stopped, stop_reason = False, ''
            for folder, sources in groups.items():
                if self.stop_event.is_set():
                    break
                by_id = {x['video_id']: x for x in sources}
                versions = retry_versions[folder] if retry else {}
                def folder_failures(stage, message, *, retryable, manifest=''):
                    return [{'batch_folder': folder, 'video_id': x['video_id'], 'name': x['name'],
                             'version': version, 'stage': stage, 'error': message,
                             'retryable': retryable, 'manifest': manifest}
                            for x in sources
                            for version in (versions[x['video_id']] if retry else range(1, options.variants + 1))]
                try:
                    # Recheck the batch at execution time, not just import time.
                    RecreationBatch.load(folder, recover_interrupted=False)
                except (OSError, ValueError):
                    failed.extend(folder_failures('读取批次', '来源批次记录不可用，已跳过此批次', retryable=True))
                    continue
                try:
                    result = generate_variants(sources, Path(folder) / '加工成品', options,
                        progress=task.progress.emit, should_stop=self.stop_event.is_set, resolved_plans=frozen_plans,
                        **({'versions_by_id': versions} if retry else {}))
                except OSError:
                    failed.extend(folder_failures('写入加工目录', '无法写入文件或加工记录；请先检查权限及可能已生成的成品',
                        retryable=False, manifest=str(Path(folder) / '加工成品')))
                    continue
                failed.extend({**entry, 'batch_folder': folder, 'name': by_id[entry['video_id']]['name'],
                               'retryable': entry.get('retryable', True),
                               'stage': entry.get('stage', '处理视频'), 'manifest': result.get('manifest', '')}
                              for entry in result['failed'])
                try:
                    if result['outputs']:
                        batch = RecreationBatch.load(folder, recover_interrupted=False)
                        batch.add_outputs(result['outputs'])
                except (OSError, ValueError):
                    failed.extend({'batch_folder': folder, 'video_id': x['source_video_id'],
                                   'name': by_id[x['source_video_id']]['name'], 'version': x['version'],
                                   'stage': '保存批次', 'error': '成品已保留；请在上传页使用“找回加工成品”恢复记录',
                                   'retryable': False, 'manifest': result.get('manifest', '')} for x in result['outputs'])
                    if result['stopped']:
                        stopped, stop_reason = True, result.get('stop_reason', '')
                        break
                    continue
                outputs.extend(result['outputs'])
                completed.update((folder, x['source_video_id'], x['version']) for x in result['outputs'])
                if result['stopped']:
                    stopped, stop_reason = True, result.get('stop_reason', '')
                    break
            return {'outputs': outputs, 'failed': failed, 'completed_keys': completed, 'retry': retry,
                    'stopped': stopped or self.stop_event.is_set(), 'stop_reason': stop_reason}
        task = Background(execute, self)
        self.task, self.busy = task, True
        task.progress.connect(self.show_progress)
        task.result.connect(self.show_result)
        if preview:
            task.failed.connect(self.status.setText)
        else:
            task.failed.connect(self.processing_interrupted)
        task.finished.connect(self.finish)
        for control in (self.table, self.options_widget, self.start_button, self.sample_button,
                        self.effect_button, self.import_button, self.remove_button):
            control.setEnabled(False)
        if self.mode=='micro':self.preview_section.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.failure_button.setEnabled(False)
        self.retry_button.setEnabled(False)
        self.bar.setRange(0, 0)
        task.start()

    def processing_interrupted(self, message):
        # An unexpected interruption gives no trustworthy per-file result. Avoid
        # retrying previously failed entries that this attempt may have completed.
        self.failures = [{**entry, 'retryable': False} for entry in self.failures]
        self.last_stop_reason = message + ' 请先检查已生成的成品及加工记录，再决定是否重跑。'
        self.status.setText('本轮中断，结果需核对；请查看失败明细。')

    def show_progress(self, event):
        if event['phase'] == 'budget_scan':
            self.status.setText(f"检查磁盘预算 · 读取视频信息 {event['index']} / {event['total']}")
            return
        if event['phase'] == 'budget':
            self.status.setText(f"预计新增 {event['estimated_bytes'] / 1048576:.1f} MB · 检查磁盘余量，另保留 256 MB…")
            return
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
        recent = {self.failure_key(entry): entry for entry in result['failed']}
        if result.get('retry'):
            merged = {self.failure_key(entry): entry for entry in self.failures
                      if self.failure_key(entry) not in result['completed_keys']}
            merged.update(recent)
            recent = merged
        self.failures = list(recent.values())
        self.last_stop_reason = (result.get('stop_reason') or '已停止') if result['stopped'] else ''
        self.status.setText(f"已入库 {len(result['outputs'])} 个 · 待处理失败 {len(self.failures)} 个"
                            + (' · ' + self.last_stop_reason if self.last_stop_reason else ''))
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
        self.failure_button.setEnabled(bool(self.failures or self.last_stop_reason))
        sources = {(item['batch_folder'], item['video_id']) for item in self.items}
        self.retry_button.setEnabled(any(entry['retryable'] and self.failure_key(entry)[:2] in sources
                                         for entry in self.failures))
        self.finished.emit()

    def stop(self):
        self.stop_event.set()
        self.stop_button.setEnabled(False)
        self.status.setText('正在停止，已完成成品保留…')

    def remove_selected(self):
        if self.owner.work_in_progress():
            return
        remove = {(self.items[i]['batch_folder'], self.items[i]['video_id'])
                  for i in self.owner.checked_rows(self.table)}
        previous = self.owner.workspace.inputs[self.mode]
        self.owner.workspace.inputs[self.mode] = [x for x in previous
            if (x['folder'], x['video_id']) not in remove]
        try:
            self.owner.workspace.save()
            self.refresh()
        except OSError:
            self.owner.workspace.inputs[self.mode] = previous
            self.status.setText('未能保存列表，请检查目录权限')
