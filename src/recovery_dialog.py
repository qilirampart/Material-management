"""Cancelable background inspection, followed by explicit product recovery."""
import threading
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QTableWidget,QTableWidgetItem,
    QHeaderView,QProgressBar,QAbstractItemView)
from src.ui_design import label,btn,Background
from src.media import FFmpegCancelled,FFmpegError
from src.recreation_recovery import inspect_manifest_recovery,commit_manifest_recovery


class RecoveryDialog(QDialog):
    def __init__(self,manifest,parent=None):
        super().__init__(parent)
        self.setWindowTitle('找回加工成品');self.resize(880,560)
        self.manifest=manifest;self.plan=None;self.busy=False;self.task=None
        self.stop_event=threading.Event();self.pending_close=None;self.saved_batch=None;self.saved_count=0
        outer=QVBoxLayout(self);outer.addWidget(label('找回加工成品','heading'))
        outer.addWidget(label('只检查和补回成品记录，不转码、不移动原文件、不上传。'))
        self.batch_label=label('读取来源批次…');outer.addWidget(self.batch_label)
        self.table=QTableWidget(0,5);self.table.setHorizontalHeaderLabels(['勾选','剧目','类型','成品','检查结果'])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers);self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(3,QHeaderView.Stretch)
        for col,width in ((0,50),(1,130),(2,70),(4,220)):self.table.setColumnWidth(col,width)
        self.table.itemChanged.connect(self.update_selection);outer.addWidget(self.table,1)
        choices=QHBoxLayout();self.all_button=btn('全选可恢复',lambda:self.select_ready(True))
        self.none_button=btn('清除勾选',lambda:self.select_ready(False))
        choices.addWidget(self.all_button);choices.addWidget(self.none_button);choices.addStretch()
        self.count_label=label('');choices.addWidget(self.count_label);outer.addLayout(choices)
        self.bar=QProgressBar();outer.addWidget(self.bar)
        self.status=label('正在检查视频与加工记录…');outer.addWidget(self.status)
        actions=QHBoxLayout();actions.addStretch();self.close_button=btn('停止并关闭',self.reject)
        self.save_button=btn('恢复勾选成品',self.restore_selected,True)
        actions.addWidget(self.close_button);actions.addWidget(self.save_button);outer.addLayout(actions)
        self.start('inspect')

    def checked(self):
        if not self.plan:return []
        return [i for i,entry in enumerate(self.plan['entries']) if entry['status']=='ready'
            and self.table.item(i,0).checkState()==Qt.Checked]

    def update_selection(self,*_):
        count=len(self.checked());self.count_label.setText(f'已勾选 {count} 条')
        self.save_button.setEnabled(bool(count) and not self.busy)

    def select_ready(self,checked):
        if self.busy or not self.plan:return
        for i,entry in enumerate(self.plan['entries']):
            if entry['status']=='ready':self.table.item(i,0).setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def start(self,phase,indexes=None):
        self.phase=phase;self.busy=True;self.stop_event.clear()
        self.table.setEnabled(False);self.all_button.setEnabled(False);self.none_button.setEnabled(False)
        self.save_button.setEnabled(False);self.bar.setRange(0,0)
        self.close_button.setText('停止并关闭' if phase=='inspect' else '保存后关闭')
        def execute():
            try:
                if self.stop_event.is_set():return {'stopped':True}
                if phase=='inspect':return {'plan':inspect_manifest_recovery(self.manifest,
                    should_stop=self.stop_event.is_set,progress=self.task.progress.emit)}
                batch,count=commit_manifest_recovery(self.plan,indexes)
                return {'batch':batch,'count':count,'indexes':indexes}
            except FFmpegCancelled:return {'stopped':True}
            except (OSError,ValueError,FFmpegError) as exc:return {'error':str(exc)[-500:]}
        self.task=Background(execute,self);self.task.result.connect(self.show_result)
        self.task.failed.connect(self.status.setText);self.task.progress.connect(self.progress)
        self.task.finished.connect(self.finished_operation);self.task.start()

    def progress(self,event):
        self.bar.setRange(0,max(1,event['total']));self.bar.setValue(event['index'])
        self.status.setText(f"正在检查 {event['index']} / {event['total']}；可停止，不会改写文件。")

    def populate(self):
        self.table.blockSignals(True);entries=self.plan['entries'];self.table.setRowCount(len(entries))
        for i,entry in enumerate(entries):
            check=QTableWidgetItem();check.setFlags(Qt.ItemIsEnabled | (Qt.ItemIsUserCheckable if entry['status']=='ready' else Qt.NoItemFlags))
            check.setCheckState(Qt.Checked if entry['status']=='ready' else Qt.Unchecked);self.table.setItem(i,0,check)
            for col,value in enumerate((entry['drama'],'微创新' if entry['mode']=='micro' else '改 MD5' if entry['mode']=='md5' else '未知',
                    Path(entry['path']).name,entry['reason']),1):
                cell=QTableWidgetItem(value);cell.setToolTip(entry['path'] if col==3 else value);self.table.setItem(i,col,cell)
        self.table.blockSignals(False)

    def show_result(self,result):
        if 'error' in result:
            self.status.setText(('检查失败：' if self.phase=='inspect' else '保存失败，视频保留，可重试：')+result['error']);return
        if result.get('stopped'):self.status.setText('已停止检查，未恢复成品。');return
        if 'plan' in result:
            self.plan=result['plan'];self.batch_label.setText('来源批次：'+self.plan['batch_name']+' · '+self.plan['batch_folder'])
            self.populate();entries=self.plan['entries']
            ready=sum(x['status']=='ready' for x in entries);duplicate=sum(x['status']=='duplicate' for x in entries)
            self.status.setText(f'可恢复 {ready} 条 · 已存在 {duplicate} 条 · 不可恢复 {len(entries)-ready-duplicate} 条；勾选后恢复。')
        elif 'batch' in result:
            self.saved_batch=result['batch'];self.saved_count+=result['count']
            for i in result['indexes']:self.plan['entries'][i].update(status='duplicate',reason='已恢复／已在成品列表')
            self.populate();self.status.setText(f"已恢复 {result['count']} 条，累计 {self.saved_count} 条；关闭后可在成品列表查看。")

    def finished_operation(self):
        self.busy=False;self.table.setEnabled(True);self.all_button.setEnabled(True);self.none_button.setEnabled(True)
        self.close_button.setText('关闭');self.bar.setRange(0,1);self.bar.setValue(1);self.update_selection()
        if self.pending_close is not None:self.done(self.pending_close)

    def restore_selected(self):
        if self.busy:return
        indexes=self.checked()
        if not indexes:return
        self.status.setText('正在保存成品记录…');self.start('save',indexes)

    def done(self,result):
        if self.busy:
            self.pending_close=result;self.stop_event.set()
            self.status.setText('正在停止检查…' if self.phase=='inspect' else '正在完成本次保存，随后关闭…');return
        super().done(result)
