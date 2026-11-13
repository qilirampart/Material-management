"""Source-frame rectangle selection; decoding stays off the GUI thread."""
import threading
import tempfile
import subprocess
from copy import deepcopy
from pathlib import Path
from PySide6.QtCore import Qt,QRectF,Signal
from PySide6.QtGui import QImage,QPainter,QColor,QPen
from PySide6.QtWidgets import (QDialog,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QListWidget,
    QScrollArea,QComboBox,QCheckBox,QDoubleSpinBox)
from src.ui_design import btn,label,Background
from src.variant_dialog import VariantDialog
from src.media import run,probe,FFmpegCancelled,FFmpegError
from src.region_effects import DEFAULT_REGION,normalize_region,validate_crop


class RegionCanvas(QWidget):
    rectangle_drawn=Signal(object)
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setMinimumSize(320,260)
        self.image=QImage();self.regions=[];self.selected=-1
        self.crop={'x':0,'y':0,'w':100,'h':100};self.mode='regions'
        self.drag_start=None;self.drag_end=None

    def image_rect(self):
        if self.image.isNull():return QRectF()
        size=self.image.size().scaled(max(1,self.width()-16),max(1,self.height()-16),Qt.KeepAspectRatio)
        return QRectF((self.width()-size.width())/2,(self.height()-size.height())/2,size.width(),size.height())

    def relative(self,point):
        rect=self.image_rect()
        return (min(1,max(0,(point.x()-rect.x())/rect.width())),
                min(1,max(0,(point.y()-rect.y())/rect.height())))

    def screen_rect(self,value):
        base=self.image_rect()
        return QRectF(base.x()+base.width()*value['x']/100,base.y()+base.height()*value['y']/100,
                      base.width()*value['w']/100,base.height()*value['h']/100)

    def dragged_rect(self):
        x=round(min(self.drag_start[0],self.drag_end[0])*100,2)
        y=round(min(self.drag_start[1],self.drag_end[1])*100,2)
        right=round(max(self.drag_start[0],self.drag_end[0])*100,2)
        bottom=round(max(self.drag_start[1],self.drag_end[1])*100,2)
        return {'x':x,'y':y,'w':round(right-x,2),'h':round(bottom-y,2)}

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton and self.image_rect().contains(event.position()):
            self.drag_start=self.drag_end=self.relative(event.position());self.update()

    def mouseMoveEvent(self,event):
        if self.drag_start is not None:self.drag_end=self.relative(event.position());self.update()

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.LeftButton and self.drag_start is not None:
            self.drag_end=self.relative(event.position());value=self.dragged_rect()
            self.drag_start=self.drag_end=None
            if value['w']>=1 and value['h']>=1:self.rectangle_drawn.emit(value)
            self.update()

    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),QColor('#18272C'))
        if self.image.isNull():
            painter.setPen(Qt.white);painter.drawText(self.rect(),Qt.AlignCenter,'读取原片画面后拖动框选');return
        painter.drawImage(self.image_rect(),self.image)
        base=self.image_rect();keep=self.screen_rect(self.crop)
        painter.setPen(Qt.NoPen);painter.setBrush(QColor(0,0,0,115))
        for rect in (QRectF(base.left(),base.top(),base.width(),keep.top()-base.top()),
            QRectF(base.left(),keep.bottom(),base.width(),base.bottom()-keep.bottom()),
            QRectF(base.left(),keep.top(),keep.left()-base.left(),keep.height()),
            QRectF(keep.right(),keep.top(),base.right()-keep.right(),keep.height())):
            painter.drawRect(rect)
        painter.setBrush(Qt.NoBrush);painter.setPen(QPen(QColor('#63E6A4'),2));painter.drawRect(keep)
        for i,region in enumerate(self.regions):
            color=QColor({'blur':'#FFE05D','cover':'#FF7777','repair':'#63C7FF'}[region['mode']])
            if not region.get('enabled',True):color=QColor('#95A0A5')
            painter.setPen(QPen(color,3 if i==self.selected else 1));painter.setBrush(Qt.NoBrush)
            rect=self.screen_rect(region);painter.drawRect(rect)
            painter.drawText(rect.adjusted(3,2,0,0),Qt.AlignLeft|Qt.AlignTop,str(i+1))
        if self.drag_start is not None:
            painter.setPen(QPen(Qt.white,2,Qt.DashLine));painter.drawRect(self.screen_rect(self.dragged_rect()))


class RegionEditorDialog(QDialog):
    def __init__(self,source,options,parent=None,*,draw_mode='regions'):
        super().__init__(parent)
        self.setWindowTitle('原片框选与裁剪');self.resize(1060,740)
        self.source=str(source);self.regions=[normalize_region(r) for r in deepcopy(options.regions)]
        self.crop_mode=options.crop_mode
        self.edges={key:getattr(options,'crop_'+key) for key in ('left','right','top','bottom')}
        if options.crop_mode=='uniform':self.edges={key:options.crop_percent for key in self.edges}
        if draw_mode=='crop':self.crop_mode='edges'
        self.active=-1;self.loading=False;self.busy=False;self.pending_close=None;self.closed=False
        self.stop_event=threading.Event();self.task=None
        self.cache=tempfile.TemporaryDirectory(prefix='dz-region-editor-')
        outer=QVBoxLayout(self)
        outer.addWidget(label('区域按原片比例定位，先处理区域再裁剪／翻转；片头尾与独立叠片不受影响。'))
        body=QHBoxLayout();outer.addLayout(body,1)
        left=QVBoxLayout();body.addLayout(left,2)
        self.canvas=RegionCanvas();left.addWidget(self.canvas,1)
        self.draw_mode=QComboBox();self.draw_mode.addItem('拖框处理区域','regions');self.draw_mode.addItem('拖框保留画面（裁剪）','crop')
        self.draw_mode.setCurrentIndex(1 if draw_mode=='crop' else 0)
        left.addWidget(self.draw_mode)
        capture=QHBoxLayout();self.frame_time=QDoubleSpinBox();self.frame_time.setRange(0,86400)
        self.frame_time.setDecimals(2);self.frame_time.setSuffix(' 秒');self.frame_time.setKeyboardTracking(False)
        capture.addWidget(label('原片截图时间'));capture.addWidget(VariantDialog._stepper(self.frame_time,'截图时间'),1)
        self.read_button=btn('刷新画面',self.load_frame);capture.addWidget(self.read_button);left.addLayout(capture)
        self.crop_info=label('');left.addWidget(self.crop_info);left.addWidget(btn('保留全画面',self.reset_crop))
        right=QVBoxLayout();body.addLayout(right,1)
        self.listing=QListWidget();self.listing.setMaximumHeight(135);right.addWidget(self.listing)
        actions=QHBoxLayout();actions.addWidget(btn('+ 新增区域',self.add_region));actions.addWidget(btn('移除当前',self.remove_region));right.addLayout(actions)
        scroll=QScrollArea();scroll.setWidgetResizable(True);right.addWidget(scroll,1)
        self.form_widget=QWidget();scroll.setWidget(self.form_widget);form=QFormLayout(self.form_widget)
        self.fields={};mode=QComboBox()
        for text,value in [('局部模糊','blur'),('黑色遮挡','cover'),('区域修补','repair')]:mode.addItem(text,value)
        self.fields['mode']=mode;form.addRow('处理',mode)
        self.enabled=QCheckBox('启用此区域');form.addRow(self.enabled)
        for key,title,low,high,value in [('x','左边距 %',0,99,10),('y','上边距 %',0,99,10),
            ('w','宽度 %',1,100,20),('h','高度 %',1,100,10),('strength','模糊强度',2,30,6),
            ('start','开始（主体秒）',0,86400,0),('duration','持续（0=片尾）',0,86400,0)]:
            spin=QDoubleSpinBox();spin.setRange(low,high);spin.setDecimals(2);spin.setValue(value)
            spin.setSingleStep(.1);spin.setKeyboardTracking(False);self.fields[key]=spin
            form.addRow(title,VariantDialog._stepper(spin,title))
        form.addRow(label('修补是区域插值，不恢复被遮挡细节；贴边区域用模糊或遮挡。'))
        self.status=label('新增后拖框；选中已有区域可重新框选。原有旧单区设置仍独立保留。');outer.addWidget(self.status)
        footer=QHBoxLayout();footer.addStretch();footer.addWidget(btn('取消',self.reject))
        self.save_button=btn('保存选区',self.accept,True);footer.addWidget(self.save_button);outer.addLayout(footer)
        self.listing.currentRowChanged.connect(self.select_region)
        self.draw_mode.currentIndexChanged.connect(self.update_mode)
        self.canvas.rectangle_drawn.connect(self.rectangle_drawn)
        for widget in self.fields.values():
            (widget.currentIndexChanged if isinstance(widget,QComboBox) else widget.valueChanged).connect(self.edited)
        self.enabled.toggled.connect(self.edited)
        self.rebuild(0);self.update_canvas();self.update_mode();self.load_frame()

    def collect(self):
        return {**{key:(w.currentData() if isinstance(w,QComboBox) else w.value()) for key,w in self.fields.items()},
            'enabled':self.enabled.isChecked()}

    def save_active(self):
        if 0<=self.active<len(self.regions):self.regions[self.active]=self.collect()

    def rebuild(self,index):
        self.listing.blockSignals(True);self.listing.clear();self.active=-1
        for i,r in enumerate(self.regions):self.listing.addItem(f"{i+1} · "+{'blur':'模糊','cover':'遮挡','repair':'修补'}[r['mode']])
        self.listing.blockSignals(False)
        if self.regions:self.listing.setCurrentRow(min(index,len(self.regions)-1))
        else:self.form_widget.setEnabled(False)

    def select_region(self,index):
        self.save_active();self.active=index;self.loading=True
        if index>=0:
            region=self.regions[index]
            for key,w in self.fields.items():
                if isinstance(w,QComboBox):w.setCurrentIndex(w.findData(region[key]))
                else:w.setValue(region[key])
            self.enabled.setChecked(region['enabled'])
        self.loading=False;self.update_mode();self.update_canvas()

    def edited(self,*_):
        if self.loading:return
        self.save_active()
        if self.active>=0:
            self.listing.item(self.active).setText(f'{self.active+1} · '+
                {'blur':'模糊','cover':'遮挡','repair':'修补'}[self.regions[self.active]['mode']])
        self.update_mode();self.update_canvas()

    def update_mode(self,*_):
        self.canvas.mode=self.draw_mode.currentData()
        self.form_widget.setEnabled(self.active>=0 and self.canvas.mode=='regions')
        self.fields['strength'].parentWidget().setEnabled(self.fields['mode'].currentData()=='blur')

    def update_canvas(self):
        self.canvas.regions=self.regions;self.canvas.selected=self.active
        self.canvas.crop={'x':self.edges['left'],'y':self.edges['top'],
            'w':100-self.edges['left']-self.edges['right'],'h':100-self.edges['top']-self.edges['bottom']}
        self.crop_info.setText('保留框裁边：'+ ' · '.join(f'{k} {self.edges[key]:g}%' for key,k in
            [('left','左'),('right','右'),('top','上'),('bottom','下')]))
        self.canvas.update()

    def rectangle_drawn(self,value):
        if self.canvas.mode=='crop':
            self.crop_mode='edges';self.edges={'left':value['x'],'right':round(100-value['x']-value['w'],2),
                'top':value['y'],'bottom':round(100-value['y']-value['h'],2)};self.update_canvas();return
        if self.active<0:self.add_region()
        if self.active<0:return
        self.loading=True
        for key,v in value.items():self.fields[key].setValue(v)
        self.loading=False;self.edited()

    def add_region(self):
        if len(self.regions)>=6:self.status.setText('最多添加 6 个处理区域');return
        self.save_active();self.regions.append(dict(DEFAULT_REGION));self.rebuild(len(self.regions)-1);self.update_canvas()

    def remove_region(self):
        if self.active<0:return
        index=self.active;self.regions.pop(index);self.rebuild(max(0,index-1));self.update_canvas()

    def reset_crop(self):
        self.crop_mode='edges';self.edges={key:0 for key in self.edges};self.update_canvas()

    def load_frame(self):
        if self.busy:return
        seconds=self.frame_time.value();self.stop_event.clear();self.busy=True
        self.read_button.setEnabled(False);self.save_button.setEnabled(False);self.status.setText('正在读取原片画面…')
        target=Path(self.cache.name)/'frame.png'
        def execute():
            try:
                meta=probe(self.source)
                if seconds>=meta['duration']:raise ValueError('截图时间超出原片时长')
                run(['ffmpeg','-y','-v','error','-ss',str(seconds),'-i',self.source,'-frames:v','1',
                     '-vf','scale=1280:1280:force_original_aspect_ratio=decrease',str(target)],
                    timeout=30,should_stop=self.stop_event.is_set)
                return {'path':str(target),'duration':meta['duration']}
            except FFmpegCancelled:return {'cancelled':True}
            except (OSError,ValueError,FFmpegError,subprocess.SubprocessError) as exc:return {'error':str(exc)[-500:]}
        if self.task:self.task.deleteLater()
        self.task=Background(execute,self);self.task.result.connect(self.frame_result)
        self.task.failed.connect(self.status.setText)
        self.task.finished.connect(self.frame_finished);self.task.start()

    def frame_result(self,result):
        if self.pending_close is not None:return
        if result.get('path'):
            image=QImage(result['path'])
            if image.isNull():self.status.setText('未能读取截图，请更换截图时间');return
            self.canvas.image=image;self.canvas.update()
            self.frame_time.setMaximum(max(0,result['duration']-.05))
            self.status.setText('拖框设置区域或保留画面；保存后回主界面预览实际处理效果。')
        elif result.get('error'):self.status.setText('读取失败：'+result['error'])

    def frame_finished(self):
        self.busy=False;self.read_button.setEnabled(True);self.save_button.setEnabled(not self.canvas.image.isNull())
        if self.pending_close is not None:self.done(self.pending_close)

    def accept(self):
        if self.busy:return
        self.save_active()
        try:
            self.regions=[normalize_region(r) for r in self.regions]
            from types import SimpleNamespace
            validate_crop(SimpleNamespace(crop_mode=self.crop_mode,**{'crop_'+k:v for k,v in self.edges.items()}))
        except ValueError as exc:self.status.setText(str(exc));return
        super().accept()

    def done(self,result):
        if self.busy:
            self.pending_close=result;self.stop_event.set();self.status.setText('正在关闭，等待截图任务结束…');return
        if not self.closed:
            self.closed=True;self.listing.blockSignals(True);self.draw_mode.blockSignals(True)
            for w in self.fields.values():w.blockSignals(True)
            self.enabled.blockSignals(True);self.cache.cleanup()
        super().done(result)
