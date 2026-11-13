"""Small multi-track editor; changes are applied only when the user saves."""
from copy import deepcopy
from PySide6.QtWidgets import (QDialog,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QListWidget,
    QPlainTextEdit,QComboBox,QSpinBox,QDoubleSpinBox,QCheckBox,QScrollArea,QColorDialog)
from src.ui_design import btn,label
from src.variant_dialog import VariantDialog
from src.text_tracks import DEFAULT_TRACK,normalize_track


class TextTracksDialog(QDialog):
    def __init__(self,tracks,parent=None):
        super().__init__(parent)
        self.setWindowTitle('多文字轨')
        self.resize(900,680)
        self.tracks=deepcopy(tracks)
        self.active=-1
        self.loading=False
        self.connections_closed=False
        outer=QVBoxLayout(self)
        outer.addWidget(label('时间从主体（去头尾／变速后）0 秒计算；片头尾不叠加这些文字。'))
        body=QHBoxLayout();outer.addLayout(body,1)
        left=QVBoxLayout();body.addLayout(left,1)
        self.listing=QListWidget();left.addWidget(self.listing,1)
        left.addWidget(btn('+ 添加文字轨',self.add_track))
        left.addWidget(btn('移除当前轨',self.remove_track))
        scroll=QScrollArea();scroll.setWidgetResizable(True);body.addWidget(scroll,3)
        self.form_widget=QWidget();scroll.setWidget(self.form_widget)
        form=QFormLayout(self.form_widget)
        self.text=QPlainTextEdit();self.text.setMaximumHeight(90)
        self.text.setPlaceholderText('最多 160 字、3 行；支持 {剧名}、{文件名}')
        form.addRow('文字',self.text)
        variables=QHBoxLayout()
        variables.addWidget(btn('插入剧名',lambda:self.text.insertPlainText('{剧名}')))
        variables.addWidget(btn('插入文件名',lambda:self.text.insertPlainText('{文件名}')))
        form.addRow(variables)
        self.fields={}
        self.combo(form,'字体','font_name',[('默认中文','default'),('黑体','sans'),('宋体','serif')])
        self.number(form,'字号','font_size',12,96,28,integer=True)
        colors=QHBoxLayout()
        color=self.combo(None,'','font_color',[('白色','FFFFFF'),('黄色','FFE05D'),('黑色','202020'),
            ('红色','FF5555'),('青色','63E6D7')])
        colors.addWidget(color,1);colors.addWidget(btn('自选颜色',self.choose_color));form.addRow('颜色',colors)
        self.combo(form,'位置','position',[('顶部居中','top'),('底部居中','bottom'),('画面中心','center'),
            ('左上','top_left'),('右上','top_right'),('左下','bottom_left'),('右下','bottom_right'),('自定义','custom')])
        self.number(form,'水平位置（0–1）','x',0,1,.5)
        self.number(form,'垂直位置（0–1）','y',0,1,.5)
        self.number(form,'不透明度（0–1）','opacity',.1,1,1)
        self.number(form,'黑色描边宽度','outline',0,8,2)
        self.number(form,'黑色阴影距离','shadow',0,8,0)
        self.box=QCheckBox('添加半透明黑色底条');form.addRow(self.box)
        self.number(form,'开始时间（秒）','start',0,86400,0)
        self.number(form,'持续时间（0=到片尾）','duration',0,86400,0)
        self.combo(form,'滚动','scroll',[('固定','none'),('向左','left'),('向右','right'),('向上','up'),('向下','down')])
        self.number(form,'滚动速度（像素／秒）','scroll_speed',10,300,60)
        self.loop=QCheckBox('循环滚动');form.addRow(self.loop)
        self.fields['position'].currentIndexChanged.connect(self.update_enabled)
        self.fields['scroll'].currentIndexChanged.connect(self.update_enabled)
        self.status=label('最多 6 条；原有单行文字独立保留。保存后可在主界面预览。');outer.addWidget(self.status)
        actions=QHBoxLayout();actions.addStretch();actions.addWidget(btn('取消',self.reject))
        actions.addWidget(btn('保存文字轨',self.accept,True));outer.addLayout(actions)
        self.listing.currentRowChanged.connect(self.select_track)
        self.text.textChanged.connect(self.update_label)
        self.rebuild(0)

    def combo(self,form,title,key,items):
        widget=QComboBox()
        for text,value in items:widget.addItem(text,value)
        self.fields[key]=widget
        if form is not None:form.addRow(title,widget)
        return widget

    def number(self,form,title,key,low,high,value,integer=False):
        widget=QSpinBox() if integer else QDoubleSpinBox()
        widget.setRange(low,high);widget.setValue(value);widget.setKeyboardTracking(False)
        if not integer:widget.setSingleStep(.1);widget.setDecimals(2)
        self.fields[key]=widget
        form.addRow(title,VariantDialog._stepper(widget,title))

    def collect(self):
        values={key:(w.currentData() if isinstance(w,QComboBox) else w.value()) for key,w in self.fields.items()}
        return dict(values,text=self.text.toPlainText(),box=self.box.isChecked(),loop=self.loop.isChecked())

    def save_active(self):
        if 0<=self.active<len(self.tracks):self.tracks[self.active]=self.collect()

    def select_track(self,index):
        self.save_active();self.active=index
        self.form_widget.setEnabled(index>=0)
        if index<0:return
        self.loading=True
        values={**DEFAULT_TRACK,**self.tracks[index]}
        self.text.setPlainText(values['text']);self.box.setChecked(values['box']);self.loop.setChecked(values['loop'])
        for key,w in self.fields.items():
            if isinstance(w,QComboBox):
                found=w.findData(values[key])
                if found<0:w.addItem('#'+values[key],values[key]);found=w.count()-1
                w.setCurrentIndex(found)
            else:w.setValue(values[key])
        self.loading=False;self.update_enabled()

    def rebuild(self,index):
        self.listing.blockSignals(True);self.listing.clear()
        for i,track in enumerate(self.tracks):
            self.listing.addItem(f"{i+1} · {track['text'].splitlines()[0][:18] if track['text'].strip() else '未填写'}")
        self.listing.blockSignals(False);self.active=-1
        if self.tracks:self.listing.setCurrentRow(min(index,len(self.tracks)-1))
        else:self.form_widget.setEnabled(False)

    def update_label(self):
        if self.loading or self.active<0:return
        text=self.text.toPlainText().splitlines()
        self.listing.item(self.active).setText(f"{self.active+1} · {text[0][:18] if text else '未填写'}")

    def add_track(self):
        if len(self.tracks)>=6:self.status.setText('最多添加 6 条文字轨');return
        self.save_active()
        positions=['top','bottom','center','top_left','bottom_right','bottom_left']
        self.tracks.append(dict(DEFAULT_TRACK,text='新文字',position=positions[len(self.tracks)]))
        self.rebuild(len(self.tracks)-1)

    def remove_track(self):
        if self.active<0:return
        index=self.active;self.tracks.pop(index);self.rebuild(max(0,index-1))

    def update_enabled(self):
        for key in ('x','y'):self.fields[key].parentWidget().setEnabled(self.fields['position'].currentData()=='custom')
        self.fields['scroll_speed'].parentWidget().setEnabled(self.fields['scroll'].currentData()!='none')
        self.loop.setEnabled(self.fields['scroll'].currentData()!='none')

    def choose_color(self):
        color=QColorDialog.getColor(parent=self)
        if color.isValid():
            widget=self.fields['font_color'];value=color.name()[1:].upper()
            widget.addItem('#'+value,value);widget.setCurrentIndex(widget.count()-1)

    def accept(self):
        self.save_active()
        try:self.tracks=[normalize_track(t) for t in self.tracks]
        except ValueError as exc:self.status.setText(str(exc));return
        super().accept()

    def done(self,result):
        # QListWidget clears its selection during destruction, after form widgets may be gone.
        if not self.connections_closed:
            self.listing.currentRowChanged.disconnect(self.select_track)
            self.text.textChanged.disconnect(self.update_label)
            for key in ('position','scroll'):
                self.fields[key].currentIndexChanged.disconnect(self.update_enabled)
            self.connections_closed=True
        super().done(result)
