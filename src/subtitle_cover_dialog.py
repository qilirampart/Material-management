"""Working-copy editor; accepting changes never starts rendering."""
from types import SimpleNamespace
from PySide6.QtWidgets import (QDialog,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QTabWidget,
    QScrollArea,QComboBox,QDoubleSpinBox,QCheckBox,QLineEdit,QFileDialog)
from src.subtitle_cover import SUBTITLE_DEFAULTS,validate_assets
from src.variant_dialog import VariantDialog
from src.ui_design import btn,label


class SubtitleCoverDialog(QDialog):
    def __init__(self,values,parent=None):
        super().__init__(parent)
        self.setWindowTitle('字幕与封面');self.resize(680,650)
        self.settings={k:values.get(k,v) for k,v in SUBTITLE_DEFAULTS.items()};self.fields={}
        outer=QVBoxLayout(self);outer.addWidget(label('字幕与封面','heading'))
        self.tabs=QTabWidget();outer.addWidget(self.tabs,1)
        subtitles=self.page('字幕烧录')
        self.file(subtitles,'字幕文件','subtitle_path','字幕 (*.srt *.ass)')
        self.combo(subtitles,'文件编码','subtitle_encoding',[('UTF-8','utf-8'),('简体中文 GB18030','gb18030'),('UTF-16','utf-16')])
        self.combo(subtitles,'字幕时间轴','subtitle_timing',[('对应原片（自动跟随裁剪与变速）','source'),('对应加工后主体','body')])
        self.number(subtitles,'整体延后','subtitle_shift',-300,300,' 秒')
        subtitles.addRow(label('负数提前。同一字幕用于本次全部视频；只烧录到主体，不移除画面原有字幕。'))
        self.keep=QCheckBox('ASS 文件保留原有样式（SRT 使用下方样式）')
        self.keep.setChecked(self.settings['subtitle_keep_ass_style']);subtitles.addRow(self.keep)
        self.style_widget=QWidget();style=QFormLayout(self.style_widget);style.setContentsMargins(0,0,0,0)
        self.number(style,'字号','subtitle_size',16,64,' px',0)
        self.fields['subtitle_color']=QLineEdit(self.settings['subtitle_color']);self.fields['subtitle_color'].setMaxLength(6)
        style.addRow('颜色（六位色值）',self.fields['subtitle_color'])
        self.number(style,'黑色描边','subtitle_outline',0,8,' px',1)
        self.number(style,'上下边距','subtitle_margin',0,200,' px',0)
        self.combo(style,'字幕位置','subtitle_position',[('底部居中','bottom'),('顶部居中','top')])
        subtitles.addRow(self.style_widget)
        self.fields['subtitle_path'].textChanged.connect(self.refresh_enabled)
        self.keep.toggled.connect(self.refresh_enabled)
        cover=self.page('封面')
        self.combo(cover,'封面来源','cover_mode',[('不使用封面','none'),('本地图片','image'),('从原片取帧','frame')])
        self.file(cover,'封面图片','cover_path','图片 (*.png *.jpg *.jpeg *.webp)')
        self.number(cover,'原片取帧位置','cover_time',0,86400,' 秒')
        self.combo(cover,'适配方式','cover_fit',[('完整显示，留黑边','contain'),('铺满画布，裁掉边缘','fill')])
        self.number(cover,'封面展示','cover_duration',.1,3,' 秒')
        cover.addRow(label('替换最终成片开头画面，声音继续，不增加时长。另存同名 .cover.png；平台封面仍需在平台确认。'))
        cover.addRow(label('在主面板点击“预览当前效果”，起点设为 0；使用片头时选择“片头转场”预览封面。'))
        self.fields['cover_mode'].currentIndexChanged.connect(self.refresh_enabled)
        self.status=label('');outer.addWidget(self.status)
        row=QHBoxLayout();row.addStretch();row.addWidget(btn('取消',self.reject));row.addWidget(btn('保留设置',self.save,True));outer.addLayout(row)
        self.refresh_enabled()

    def page(self,name):
        scroll=QScrollArea();scroll.setWidgetResizable(True);page=QWidget();form=QFormLayout(page)
        form.setSpacing(12);scroll.setWidget(page);self.tabs.addTab(scroll,name);return form

    def combo(self,form,title,key,choices):
        widget=QComboBox()
        for text,value in choices:widget.addItem(text,value)
        widget.setCurrentIndex(widget.findData(self.settings[key]));self.fields[key]=widget;form.addRow(title,widget)

    def number(self,form,title,key,low,high,suffix='',decimals=2):
        widget=QDoubleSpinBox();widget.setRange(low,high);widget.setDecimals(decimals)
        widget.setSingleStep(.1 if decimals else 1);widget.setSuffix(suffix);widget.setValue(self.settings[key]);widget.setKeyboardTracking(False)
        self.fields[key]=widget;form.addRow(title,VariantDialog._stepper(widget,title))

    def file(self,form,title,key,filters):
        wrapper=QWidget();row=QHBoxLayout(wrapper);row.setContentsMargins(0,0,0,0)
        text=QLineEdit(self.settings[key]);text.setPlaceholderText('可选，本地文件');self.fields[key]=text
        def choose():
            path,_=QFileDialog.getOpenFileName(self,title,'',filters)
            if path:text.setText(path)
        row.addWidget(text,1);row.addWidget(btn('浏览',choose));form.addRow(title,wrapper)

    def refresh_enabled(self,*_):
        ass=self.fields['subtitle_path'].text().lower().endswith('.ass')
        self.style_widget.setEnabled(not (ass and self.keep.isChecked()))
        mode=self.fields['cover_mode'].currentData()
        self.fields['cover_path'].parentWidget().setEnabled(mode=='image')
        self.fields['cover_time'].parentWidget().setEnabled(mode=='frame')
        self.fields['cover_fit'].setEnabled(mode!='none');self.fields['cover_duration'].parentWidget().setEnabled(mode!='none')

    def values(self):
        values={}
        for key,w in self.fields.items():
            values[key]=w.currentData() if isinstance(w,QComboBox) else w.text().strip() if isinstance(w,QLineEdit) else w.value()
        values['subtitle_keep_ass_style']=self.keep.isChecked()
        return values

    def save(self):
        values=self.values()
        try:validate_assets(SimpleNamespace(**values))
        except ValueError as exc:self.status.setText(str(exc));return
        self.settings=values;self.accept()
