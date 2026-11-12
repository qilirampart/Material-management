"""Composable micro-innovation controls; every enabled control maps to VariantOptions."""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget,
    QComboBox, QDoubleSpinBox, QSpinBox, QCheckBox, QLineEdit, QFileDialog)
from src.variant_dialog import VariantDialog
from src.ui_design import label, btn


class MicroSettings(QWidget):
    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setMinimumHeight(350)
        outer.addWidget(self.tabs)
        self.fields = {}
        picture = self.page('画面')
        preset = QComboBox()
        self.resolution_preset = preset
        for name, size in [('竖屏 720×1280', (720,1280)), ('竖屏 1080×1920', (1080,1920)),
                           ('横屏 1280×720', (1280,720)), ('横屏 1920×1080', (1920,1080)), ('自定义', None)]:
            preset.addItem(name, size)
        picture.addRow('输出尺寸', preset)
        self.width = self.integer(240,3840,720,step=2)
        self.height = self.integer(240,3840,1280,step=2)
        picture.addRow('宽度', self.step(self.width,'输出宽度'))
        picture.addRow('高度', self.step(self.height,'输出高度'))
        def apply_preset():
            size = preset.currentData()
            if size:
                self.width.setValue(size[0]); self.height.setValue(size[1])
            self.width.parentWidget().setEnabled(size is None)
            self.height.parentWidget().setEnabled(size is None)
        preset.currentIndexChanged.connect(apply_preset)
        apply_preset()
        self.combo(picture,'画布背景','background', [('模糊背景','blur'),('黑边背景','black')])
        self.number(picture,'前景占比','foreground_scale',50,100,90,' %',100,0,1)
        self.combo(picture,'画面位置','vertical_position', [('居中',.5),('偏上',.25),('贴顶',0),('偏下',.75),('贴底',1)])
        self.combo(picture,'旋转','rotation',[('不旋转',0),('顺时针 90°',90),('180°',180),('逆时针 90°',270)])
        self.mirror = QCheckBox('水平镜像')
        picture.addRow(self.mirror)
        self.number(picture,'四周裁边','crop_percent',0,15,0,' %',1,1,.5)
        picture.addRow(label('裁边、镜像可能影响字幕，请先看样片。'))

        color = self.page('调色')
        self.color = QCheckBox('启用调色；多版本使用不同轻度扰动')
        self.color.setChecked(True)
        color.addRow(self.color)
        for title,key,low,high,value,step in [('亮度','brightness',-.2,.2,0,.01),('对比度','contrast',.5,1.5,1,.01),
                                            ('饱和度','saturation',0,2,1,.05)]:
            self.number(color,title,key,low,high,value,'',1,2,step)
        self.color.toggled.connect(lambda enabled: [self.fields[k].parentWidget().setEnabled(enabled)
                                                    for k in ('brightness','contrast','saturation')])
        self.number(color,'锐化','sharpen',0,2,0,'',1,1,.1)
        self.number(color,'降噪','denoise',0,10,0,'',1,1,.5)
        color.addRow(label('0 表示不锐化／不降噪；增强过多可能损失细节。'))

        timing = self.page('时间')
        self.trim_start = self.number(timing,'去掉开头','trim_start',0,60,.15,' 秒',1,2,.01)
        self.trim_end = self.number(timing,'去掉结尾','trim_end',0,60,.15,' 秒',1,2,.01)
        self.speed = self.number(timing,'播放速度','speed',.8,1.2,1.02,' 倍',1,2,.01)
        self.combo(timing,'输出帧率','output_fps',[('跟随原片',0),('24 fps',24),('25 fps',25),('30 fps',30),('50 fps',50),('60 fps',60)])
        self.drop_enabled = QCheckBox('启用间隔抽帧')
        timing.addRow(self.drop_enabled)
        self.drop_every = self.integer(2,300,25)
        self.drop_every.setSuffix(' 帧')
        timing.addRow('每 N 帧去掉 1 帧', self.step(self.drop_every,'抽帧间隔'))
        self.drop_every.parentWidget().setEnabled(False)
        self.drop_enabled.toggled.connect(self.drop_every.parentWidget().setEnabled)
        timing.addRow(label('抽帧保留时间轴，由相邻帧补齐，不剪掉剧情时间；变速保持音高。'))

        watermark = self.page('水印')
        self.title = QLineEdit()
        self.title.setMaxLength(40)
        self.title.setPlaceholderText('可选，一行标题或角标')
        watermark.addRow('文字',self.title)
        self.title_size = self.integer(16,64,28)
        watermark.addRow('字号',self.step(self.title_size,'字号'))
        positions=[('顶部居中','top'),('底部居中','bottom'),('左上角','top_left'),('右上角','top_right'),
                   ('左下角','bottom_left'),('右下角','bottom_right')]
        self.combo(watermark,'文字位置','title_position',positions)
        self.combo(watermark,'文字颜色','title_color',[('白色','FFFFFF'),('黄色','FFE05D'),('黑色','202020')])
        self.watermark_path = self.file_picker(watermark,'图片水印','图片 (*.png *.jpg *.jpeg *.webp)')
        self.combo(watermark,'图片位置','watermark_position', [positions[3],positions[0],positions[1],positions[2],positions[4],positions[5]])
        self.number(watermark,'图片宽度占比','watermark_scale',5,50,15,' %',100,0,1)
        self.number(watermark,'图片不透明度','watermark_opacity',10,100,80,' %',100,0,5)

        audio = self.page('音频')
        self.audio_mode = self.combo(audio,'处理方式','audio_mode',[('保留原声','original'),('静音','mute'),
            ('混入背景音乐','mix'),('仅背景音乐','replace')])
        self.music_path = self.file_picker(audio,'背景音乐','音频 (*.mp3 *.wav *.m4a *.aac *.flac *.ogg)')
        self.number(audio,'原声音量','original_volume',0,200,100,' %',100,0,5)
        self.number(audio,'音乐音量','music_volume',0,200,25,' %',100,0,5)
        def audio_enabled():
            mode=self.audio_mode.currentData()
            self.music_path.parentWidget().setEnabled(mode in {'mix','replace'})
            self.fields['music_volume'].parentWidget().setEnabled(mode in {'mix','replace'})
            self.fields['original_volume'].parentWidget().setEnabled(mode in {'mix','original'})
        self.audio_mode.currentIndexChanged.connect(audio_enabled)
        audio_enabled()
        audio.addRow(label('音乐不足会循环至视频结束。混音保留对白；仅背景音乐会去掉原声。'))

        region = self.page('区域')
        self.mask_mode=self.combo(region,'区域处理','mask_mode',[('不处理','none'),('局部模糊','blur'),('黑色遮挡','cover')])
        for title,key,low,high,value in [('左边距 X','mask_x',0,99,0),('上边距 Y','mask_y',0,99,0),
                                       ('区域宽度','mask_w',1,100,20),('区域高度','mask_h',1,100,10)]:
            self.number(region,title,key,low,high,value,' %',1,1,1)
        def mask_enabled():
            for key in ('mask_x','mask_y','mask_w','mask_h'):
                self.fields[key].parentWidget().setEnabled(self.mask_mode.currentData()!='none')
        self.mask_mode.currentIndexChanged.connect(mask_enabled)
        mask_enabled()
        region.addRow(label('以旋转、裁边后的前景画面为准；区域不能超出边界。模糊／遮挡不重建原画面。'))

    def page(self,name):
        page=QWidget()
        form=QFormLayout(page)
        form.setSpacing(9)
        self.tabs.addTab(page,name)
        return form

    @staticmethod
    def integer(low,high,value,step=1):
        spin=QSpinBox();spin.setRange(low,high);spin.setSingleStep(step);spin.setValue(value)
        spin.setKeyboardTracking(False)
        return spin

    @staticmethod
    def step(widget,name):
        return VariantDialog._stepper(widget,name)

    def number(self,form,title,key,low,high,value,suffix='',divisor=1,decimals=2,step=.01):
        spin=QDoubleSpinBox();spin.setRange(low,high);spin.setDecimals(decimals)
        spin.setSingleStep(step);spin.setValue(value);spin.setSuffix(suffix);spin.setKeyboardTracking(False)
        self.fields[key]=spin
        spin.setProperty('optionDivisor',divisor)
        form.addRow(title,self.step(spin,title))
        return spin

    def combo(self,form,title,key,items):
        combo=QComboBox()
        for text,value in items:combo.addItem(text,value)
        self.fields[key]=combo
        form.addRow(title,combo)
        return combo

    def file_picker(self,form,title,filters):
        wrapper=QWidget();row=QHBoxLayout(wrapper);row.setContentsMargins(0,0,0,0)
        text=QLineEdit();text.setPlaceholderText('可选，本地文件')
        row.addWidget(text,1)
        def choose():
            path,_=QFileDialog.getOpenFileName(self,'选择'+title,'',filters)
            if path:text.setText(path)
        row.addWidget(btn('浏览',choose))
        form.addRow(title,wrapper)
        return text

    def values(self):
        values={}
        for key,widget in self.fields.items():
            values[key]=widget.currentData() if isinstance(widget,QComboBox) else widget.value()/(widget.property('optionDivisor') or 1)
        for key in ('rotation','output_fps'):
            values[key]=int(values[key])
        values.update(output_width=self.width.value(),output_height=self.height.value(),mirror=self.mirror.isChecked(),
            color_adjust=self.color.isChecked(),title=self.title.text().strip(),title_size=self.title_size.value(),
            watermark_path=self.watermark_path.text().strip(),music_path=self.music_path.text().strip(),
            drop_every=self.drop_every.value() if self.drop_enabled.isChecked() else 0)
        return values
