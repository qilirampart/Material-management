"""Settings and Qt coordinator for the local recreation schedule."""
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTime, QTimer, QObject
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLineEdit, QScrollArea, QSpinBox, QTimeEdit, QVBoxLayout)

from src.edge_cdp import find_page_ws_url
from src.micro_settings import MicroSettings
from src.recreation import RecreationBatch
from src.recreation_platform import PlatformMaterialClient, RecreationStopped
from src.recreation_schedule import DownloadHistory, InvalidSchedule, ScheduleStore, due_window, make_schedule, run_schedule
from src.micro_presets import RECOMMENDED, RECOMMENDED_NAME, preset_references
from src.ui_design import Background, btn, label


class ScheduleDialog(QDialog):
    def __init__(self, owner, task):
        super().__init__(owner)
        self.setWindowTitle('定时扫描')
        self.setMinimumWidth(490)
        self.task = task
        self.updated = None
        self.values = None
        self.owner = owner
        self.template = label('推荐 · 明显变化')
        self.when = QTimeEdit()
        self.when.setDisplayFormat('HH:mm')
        self.when.setTime(QTime.fromString((task or {}).get('at','18:00'), 'HH:mm'))
        self.drama = QLineEdit((task or {}).get('drama',''))
        self.exclude = QLineEdit((task or {}).get('exclude','小方块'))
        self.uploader = QLineEdit()
        self.uploader.setPlaceholderText('例如 PSK')
        self.count = QSpinBox()
        self.count.setRange(1, 10)
        self.mode = QComboBox()
        for name, value in (('只下载', 'download'),('下载后改 MD5', 'md5'),('下载后微创新', 'micro')):
            self.mode.addItem(name,value)
        self.mode.setCurrentIndex(self.mode.findData((task or {}).get('mode','download')))
        self.enabled = QCheckBox('每天按时运行')
        self.enabled.setChecked((task or {}).get('enabled',True))
        self.template_settings = btn('选收藏 / 编辑参数…', self.configure_micro)
        options = (task or {}).get('options')
        if options:
            self.uploader.setText(options['uploader'])
            self.count.setValue(options['variants'])
            if options['mode']=='micro':
                self.values = {k:v for k,v in options.items() if k not in ('mode','variants','uploader')}
                self.template.setText((task or {}).get('template','已保存的模板'))
        form = QFormLayout(self)
        form.addRow(self.enabled)
        form.addRow('剧目 ID', self.drama)
        form.addRow('每天', self.when)
        form.addRow('排除名称含', self.exclude)
        form.addRow('下载后', self.mode)
        form.addRow('上传人缩写', self.uploader)
        form.addRow('每条生成', self.count)
        row = QHBoxLayout()
        row.addWidget(self.template,1)
        row.addWidget(self.template_settings)
        form.addRow('创新模板', row)
        note = label('使用本机下载历史去重。成品进入自动上传页，由你核对后上传。')
        note.setWordWrap(True)
        form.addRow(note)
        self.error = label('')
        self.error.setWordWrap(True)
        form.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText('保存任务')
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.mode.currentIndexChanged.connect(self.update_fields)
        self.update_fields()
        if (task or {}).get('pending'):
            for widget in (self.drama,self.when,self.exclude,self.mode,self.uploader,self.count,self.template_settings):
                widget.setEnabled(False)
            self.error.setText('本轮未结束，参数已锁定。可启用后继续，或先结束本轮。')
            discard = buttons.addButton('结束本轮', QDialogButtonBox.ActionRole)
            discard.clicked.connect(self.discard_pending)

    def update_fields(self):
        mode = self.mode.currentData()
        self.uploader.setEnabled(mode!='download')
        self.count.setEnabled(mode!='download')
        self.template.setEnabled(mode=='micro')
        self.template_settings.setEnabled(mode=='micro')

    def configure_micro(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('定时任务 · 微创新模板')
        dialog.resize(700, 720)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label('选用收藏后也可以直接调整。保存的是本任务的参数副本。'))
        settings = MicroSettings(presets_path=Path(self.owner.preferences_path).parent/'micro-presets.json')
        if self.values is not None:
            settings.apply_settings(self.values)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(settings)
        layout.addWidget(scroll,1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('使用这套参数')
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.Accepted:
            self.values = settings.values()
            name = settings.preset_combo.currentText()
            reference = RECOMMENDED if name==RECOMMENDED_NAME else settings.presets.get(name)
            self.template.setText(name if self.values == reference else '本任务自定义')

    def discard_pending(self):
        # Do not abandon files or their history; only retire this occurrence.
        self.updated = {**self.task, 'enabled':False,'pending':None,
                        'last_day':self.task['pending']['window'][1],'attention':False,
                        'status':'已结束本轮，已下载文件和已生成成品保留'}
        self.accept()

    def save(self):
        if (self.task or {}).get('pending'):
            self.updated = {**self.task,'enabled':self.enabled.isChecked(),'attention':False}
            self.accept()
            return
        try:
            values = self.values if self.values is not None else RECOMMENDED
            if self.mode.currentData() == 'micro' and any(not x['exists'] for x in preset_references(values)):
                raise ValueError('创新模板有资源已移动，请先重新选择文件')
            task = make_schedule(self.drama.text(), self.when.time().toString('HH:mm'),self.exclude.text(),
                self.mode.currentData(), self.uploader.text(),self.count.value(),values,datetime.now())
        except (OSError, ValueError) as exc:
            self.error.setText(str(exc))
            return
        if self.task and self.task['drama']==task['drama']:
            task.update(start=self.task['start'],last_day=self.task['last_day'],status=self.task['status'])
        self.updated = {**task,'enabled':self.enabled.isChecked(),'template':self.template.text()}
        self.accept()


class ScheduleController(QObject):
    def __init__(self, owner, layout, *, active):
        super().__init__(owner)
        self.owner = owner
        self.active = active
        self.store = ScheduleStore(owner.preferences_path.parent)
        self.history = DownloadHistory(owner.preferences_path.parent)
        self.worker = None
        self.stop_event = threading.Event()
        self.working = False
        self.editing = False
        self.browser_opened = False
        self.paused_by_user = False
        self.last_attempt = None
        row = QHBoxLayout()
        self.config = btn('定时扫描…', self.edit)
        self.stop_button = btn('暂停本轮', self.pause)
        self.stop_button.hide()
        self.status = label('')
        self.status.setWordWrap(True)
        self.status.setMinimumWidth(150)
        self.status.setMaximumWidth(290)
        row.addWidget(self.status)
        row.addWidget(self.stop_button)
        row.addWidget(self.config)
        layout.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setInterval(30000)
        self.timer.timeout.connect(self.tick)
        self.refresh()
        if active:
            self.timer.start()
            QTimer.singleShot(1000, self.tick)

    def refresh(self, override=''):
        try:
            task = self.store.load()
            heading = ('未设置定时任务' if not task else
                       f"{task['drama']} · 每天 {task['at']}" if task['enabled'] else '定时扫描已停用')
            detail = override or (task or {}).get('status','')
            self.status.setText(heading + ('\n'+detail if detail else ''))
        except (OSError, ValueError, KeyError) as exc:
            self.status.setText('定时任务无法读取：'+str(exc))

    def edit(self):
        self.editing = True
        try:
            recovering = False
            try:
                task = self.store.load()
            except InvalidSchedule:
                task = None
                recovering = True
            dialog = ScheduleDialog(self.owner,task)
            if recovering:
                dialog.error.setText('定时配置损坏。重新设置并保存后，原配置将保留为备份。')
            if dialog.exec() == QDialog.Accepted:
                if recovering:
                    self.store.rebuild(dialog.updated)
                else:
                    self.store.save(dialog.updated)
                self.last_attempt = None
                if self.active and not self.timer.isActive():
                    self.timer.start()
                self.refresh()
                if self.timer.isActive():
                    QTimer.singleShot(0,self.tick)
        except (OSError, ValueError, KeyError) as exc:
            self.refresh('定时配置未保存：'+str(exc))
        finally:
            self.editing = False

    def pause(self):
        self.paused_by_user = True
        self.stop_event.set()
        self.stop_button.setEnabled(False)
        self.refresh('正在暂停；已完成的文件保留')

    def stop_on_close(self):
        self.timer.stop()
        if self.working:
            self.stop_event.set()

    def tick(self):
        owner = self.owner
        if self.editing or self.working or owner.work_in_progress() or owner.queue_running:
            return
        now = datetime.now()
        try:
            task = self.store.load()
            window = due_window(task,now)
            if not window or task.get('attention'):
                return
            if self.last_attempt and (now-self.last_attempt).total_seconds() < 180:
                return
            browser = owner.platform.browser
            if browser is None:
                if not self.browser_opened:
                    self.browser_opened = True
                    owner.platform.open_platform()
                self.refresh('到点待扫描；如智投未登录，请打开登录页扫码')
                return
            target = browser.page().devToolsId()
            if not target:
                return
            port = owner.platform.internal_browser_debug_port
            url = owner.platform.config.get('platform_url') or owner.platform.address.text()
            folders = tuple(owner.workspace.folders)
            queued = tuple((job['folder'],tuple(job['identities'])) for job in owner.workspace.queue)
            new_batch = not task['pending']
            if new_batch:
                batch = owner.workspace.create(task['drama'])[0]
                task['pending'] = {'folder':str(batch.folder),'window':list(window)}
                self.store.save(task)
                owner.refresh_batch_list()
            else:
                folder = Path(task['pending']['folder']).resolve()
                if folder.parent != (owner.output_root/'素材再创作').resolve() or str(folder) not in folders:
                    raise ValueError('定时批次已移走或删除，请在定时任务设置里结束本轮')
                batch = RecreationBatch.load(folder)
            self.last_attempt = now
            self.stop_event.clear()
            self.paused_by_user = False
            self.working = True
            self.config.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.stop_button.show()
            self.refresh('正在扫描智投素材…')

            def work():
                ws = find_page_ws_url(url,port,target_id=target)
                stopped = self.stop_event.is_set
                client = PlatformMaterialClient(ws,should_stop=stopped)
                self.history.sync_batches(folders)
                try:
                    client.ensure_ready()
                    queued_ids = {identity for folder, identities in queued if (Path(folder)/'recreation.json').is_file()
                                  for identity in identities}
                    return run_schedule(task,batch,client,self.history,window,stopped,
                                        progress=worker.progress.emit,queued_ids=queued_ids)
                except RecreationStopped:
                    return {'done':False,'message':'本轮已暂停；已完成的文件保留'}

            worker = Background(work,self)
            self.worker = worker
            worker.progress.connect(self.progress)
            worker.result.connect(lambda result: self.save_result(task,window,result))
            worker.failed.connect(lambda message: self.save_result(task,window,{'done':False,'message':message}))
            worker.finished.connect(self.finish)
            worker.start()
        except (OSError, ValueError, KeyError) as exc:
            self.last_attempt = now
            self.refresh('定时任务未启动：'+str(exc))

    def progress(self, event):
        index,total=event.get('index',0),event.get('total',0)
        phase=event.get('phase')
        if phase in ('lookup','page'):
            self.refresh('正在查询新素材…')
        elif phase in ('resolving','downloaded','failed'):
            self.refresh(f'下载素材 {index}/{total}')
        elif phase in ('budget_scan','started','completed'):
            self.refresh(f'加工成品 {index}/{total}')

    def save_result(self, task, window, result):
        try:
            task = dict(task)
            if result['done']:
                if result.get('retry_ids'):
                    self.owner.workspace.enqueue(task['pending']['folder'],result['retry_ids'])
                task.update(last_day=window[1],pending=None)
            task['attention'] = not result['done'] and bool(result.get('attention') or self.paused_by_user)
            if self.stop_event.is_set() and not self.paused_by_user:
                task['attention'] = False
            task['status'] = result['message']
            self.store.save(task)
            self.refresh()
        except (OSError, ValueError) as exc:
            self.refresh('定时结果未保存，已暂停：'+str(exc))
            self.timer.stop()

    def finish(self):
        owner = self.owner
        self.working = False
        self.config.setEnabled(True)
        self.stop_button.hide()
        owner.refresh_batch_list()
        owner.refresh_outputs()
        owner.task_finished.emit()
