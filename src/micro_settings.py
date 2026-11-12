"""Composable micro-innovation controls; every enabled control maps to VariantOptions."""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget,
    QComboBox, QDoubleSpinBox, QSpinBox, QCheckBox, QLineEdit, QFileDialog, QInputDialog, QMessageBox)
from pathlib import Path
from src.variant_dialog import VariantDialog
from src.ui_design import label, btn
from src.micro_presets import RECOMMENDED_NAME, RECOMMENDED, read_presets, write_presets, validate_settings
from src.material_variants import VariantOptions


class MicroSettings(QWidget):
    def __init__(self, *, presets_path=None):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.presets_path = Path(presets_path) if presets_path is not None else None
        self.presets = {}
        self.preset_combo = QComboBox()
        self.preset_combo.setToolTip('选择收藏即可应用全部创新参数；不改变视频列表。')
        self.preset_combo.activated.connect(self.apply_selected_preset)
        favorites = QHBoxLayout()
        favorites.addWidget(self.preset_combo,1)
        self.favorite_button = btn('收藏当前…',self.save_favorite)
        self.favorite_button.setEnabled(self.presets_path is not None)
        favorites.addWidget(self.favorite_button)
        outer.addLayout(favorites)
        actions = QHBoxLayout()
        actions.addWidget(btn('恢复推荐',self.apply_recommended))
        self.delete_favorite_button = btn('删除收藏',self.delete_favorite)
        actions.addWidget(self.delete_favorite_button)
        actions.addStretch()
        outer.addLayout(actions)
        self.preset_status = label('')
        outer.addWidget(self.preset_status)
        self.tabs = QTabWidget()
        self.tabs.tabBar().setStyleSheet('QTabBar::tab { padding:5px 6px; }')
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
        self.combo(picture,'动态缩放','zoom_mode',[('关闭','none'),('缓慢推近','in'),('缓慢拉远','out'),('往返呼吸','pulse')])
        self.number(picture,'缩放幅度','zoom_amount',0,25,8,' %',100,0,1)
        self.number(picture,'运镜时长／周期','zoom_period',1,60,6,' 秒',1,1,.5)
        def zoom_enabled():
            for key in ('zoom_amount','zoom_period'):
                self.fields[key].parentWidget().setEnabled(self.fields['zoom_mode'].currentData()!='none')
        self.fields['zoom_mode'].currentIndexChanged.connect(zoom_enabled)
        zoom_enabled()
        picture.addRow(label('放大会裁去画布边缘；请预览检查字幕。'))

        layers=self.page('叠加')
        visual_filter='图片或视频 (*.png *.jpg *.jpeg *.webp *.mp4 *.mov *.mkv *.webm *.m4v)'
        self.background_path=self.file_picker(layers,'背景素材',visual_filter)
        layers.addRow(label('留空沿用画布背景；图片／视频铺满背景，短视频循环，忽略其声音。'))
        self.pip_path=self.file_picker(layers,'画中画素材',visual_filter)
        self.number(layers,'画中画占比','pip_scale',10,80,25,' %',100,0,1)
        self.number(layers,'水平位置','pip_x',0,100,100,' %',100,0,5)
        self.number(layers,'垂直位置','pip_y',0,100,100,' %',100,0,5)
        self.number(layers,'不透明度','pip_opacity',10,100,100,' %',100,0,5)
        layers.addRow(label('0% 为左／上，100% 为右／下；素材等比完整显示，叠片声音不混入。'))

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
        variation=self.page('多版')
        self.randomize=QCheckBox('启用随机多版本')
        variation.addRow(self.randomize)
        self.random_seed=self.integer(0,2147483647,1)
        variation.addRow('固定种子',self.step(self.random_seed,'固定种子'))
        variation.addRow(btn('换一组参数',lambda:self.random_seed.setValue((self.random_seed.value()+1)%2147483648)))
        self.range_widgets={}
        for key,title,low,high,a,b,decimals in [
            ('foreground_scale','前景占比',.5,1,.72,.88,2),('speed','播放速度',.8,1.2,1.02,1.1,2),
            ('brightness','亮度',-.2,.2,0,.04,2),('saturation','饱和度',0,2,1.05,1.2,2),
            ('contrast','对比度',.5,1.5,1.05,1.2,2),('vertical_position','垂直位置',0,1,.25,.75,2),
            ('zoom_amount','动态幅度',0,.25,.04,.12,2)]:
            wrapper=QWidget();line=QHBoxLayout(wrapper);line.setContentsMargins(0,0,0,0)
            enabled=QCheckBox();enabled.setChecked(key in {'foreground_scale','speed'})
            line.addWidget(enabled)
            pair=[]
            for value in (a,b):
                spin=QDoubleSpinBox();spin.setRange(low,high);spin.setDecimals(decimals)
                spin.setValue(value);spin.setKeyboardTracking(False)
                spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
                spin.setAccessibleName(title+('下限' if not pair else '上限'))
                line.addWidget(spin,1);pair.append(spin)
                if len(pair)==1:line.addWidget(label('至'))
            variation.addRow(title,wrapper)
            self.range_widgets[key]=(enabled,*pair)
            for spin in pair:spin.setEnabled(enabled.isChecked())
            enabled.toggled.connect(lambda checked,spins=pair:[spin.setEnabled(checked) for spin in spins])
        variation.addRow(label('前景、位置及动态幅度按比例填写，例如 0.8=80%；调色范围需启用调色，动态范围需启用运镜。'))
        self.pool_widgets={}
        for key,title in [('background_path','背景资源池'),('pip_path','叠片资源池'),
                          ('watermark_path','水印资源池'),('music_path','音乐资源池')]:
            self.pool_widgets[key]=self.file_picker(variation,title,'',directory=True)
        variation.addRow(label('文件夹只读取本层支持格式，启用后替代对应单文件；音乐池需先选择混音或仅背景音乐。种子与来源相同则可复现。'))
        def enable_default_ranges(enabled):
            if enabled and not any(w[0].isChecked() for w in self.range_widgets.values()):
                for key in ('foreground_scale','speed'):self.range_widgets[key][0].setChecked(True)
        self.randomize.toggled.connect(enable_default_ranges)
        # Keep the established first six categories in their original order.
        layers_widget=layers.parentWidget()
        self.tabs.removeTab(self.tabs.indexOf(layers_widget))
        self.tabs.insertTab(6,layers_widget,'叠加')
        try:
            self.presets = read_presets(self.presets_path) if self.presets_path else {}
        except (OSError,ValueError,TypeError) as exc:
            self.preset_status.setText('收藏未读取：'+str(exc))
        self.refresh_presets()
        self.apply_settings(RECOMMENDED)
        if not self.preset_status.text():
            self.preset_status.setText('默认：前景 80% · 增强调色 · 1.06 倍速 · 保留原声')

    def refresh_presets(self, selected=RECOMMENDED_NAME):
        self.preset_combo.clear()
        self.preset_combo.addItems([RECOMMENDED_NAME]+list(self.presets))
        self.preset_combo.setCurrentText(selected)
        self.delete_favorite_button.setEnabled(self.preset_combo.currentIndex()>0)

    def apply_settings(self, values):
        values=validate_settings(values)
        size=(values['output_width'],values['output_height'])
        index=next((i for i in range(self.resolution_preset.count())
                    if self.resolution_preset.itemData(i)==size),self.resolution_preset.count()-1)
        self.resolution_preset.setCurrentIndex(index)
        self.width.setValue(size[0]);self.height.setValue(size[1])
        for key,widget in self.fields.items():
            if isinstance(widget,QComboBox):
                widget.setCurrentIndex(widget.findData(values[key]))
            else:
                widget.setValue(values[key]*(widget.property('optionDivisor') or 1))
        self.mirror.setChecked(values['mirror']);self.color.setChecked(values['color_adjust'])
        self.title.setText(values['title']);self.title_size.setValue(values['title_size'])
        self.watermark_path.setText(values['watermark_path']);self.music_path.setText(values['music_path'])
        self.drop_enabled.setChecked(values['drop_every']>0)
        self.drop_every.setValue(values['drop_every'] or 25)
        self.background_path.setText(values['background_path']);self.pip_path.setText(values['pip_path'])
        self.randomize.setChecked(values['randomize']);self.random_seed.setValue(values['random_seed'])
        for key,(enabled,a,b) in self.range_widgets.items():
            enabled.setChecked(key in values['random_ranges'])
            if enabled.isChecked():
                a.setValue(values['random_ranges'][key][0]);b.setValue(values['random_ranges'][key][1])
        for key,widget in self.pool_widgets.items():widget.setText(values['resource_pools'].get(key,''))

    def apply_selected_preset(self, *_):
        if self.preset_combo.currentIndex()<0:
            return
        name=self.preset_combo.currentText()
        self.apply_settings(RECOMMENDED if name==RECOMMENDED_NAME else self.presets[name])
        self.preset_status.setText('已应用：'+name)
        self.delete_favorite_button.setEnabled(name!=RECOMMENDED_NAME)
        values=self.values()
        missing=[values[key] for key in ('music_path','watermark_path','background_path','pip_path')
                 if values[key] and not Path(values[key]).is_file()]
        if missing:
            self.preset_status.setText('参数已应用；配乐或水印文件已移动，请重新选择。')

    def apply_recommended(self):
        self.preset_combo.setCurrentIndex(0)
        self.apply_selected_preset()

    def save_favorite(self):
        name,ok=QInputDialog.getText(self,'收藏创新格式','给这套格式起个名字（最多 40 字）：')
        if not ok:return
        name=name.strip()
        if not name or len(name)>40 or name==RECOMMENDED_NAME:
            self.preset_status.setText('请输入 1–40 字的收藏名，不能使用推荐方案名称。')
            return
        try:
            presets=read_presets(self.presets_path)
            values=self.values()
            VariantOptions(**values).validate()
            if name in presets and QMessageBox.question(self,'覆盖收藏','已有同名收藏，是否替换？')!=QMessageBox.Yes:
                return
            presets[name]=values
            write_presets(self.presets_path,presets)
            self.presets=presets
            self.refresh_presets(name)
            self.preset_status.setText('已收藏：'+name)
        except (OSError,ValueError,TypeError) as exc:
            self.preset_status.setText('未能收藏：'+str(exc))

    def delete_favorite(self):
        name=self.preset_combo.currentText()
        if name==RECOMMENDED_NAME:return
        if QMessageBox.question(self,'删除收藏','删除收藏“'+name+'”？视频和当前参数不变。')!=QMessageBox.Yes:return
        try:
            presets=read_presets(self.presets_path)
            presets.pop(name,None)
            write_presets(self.presets_path,presets)
            self.presets=presets;self.refresh_presets()
            self.preset_combo.setCurrentIndex(-1)
            self.preset_combo.setPlaceholderText('选择收藏以应用')
            self.preset_status.setText('收藏已删除；当前参数保留。')
        except (OSError,ValueError,TypeError) as exc:
            self.preset_status.setText('未能删除收藏：'+str(exc))

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

    def file_picker(self,form,title,filters,directory=False):
        wrapper=QWidget();row=QHBoxLayout(wrapper);row.setContentsMargins(0,0,0,0)
        text=QLineEdit();text.setPlaceholderText('可选，本地文件')
        row.addWidget(text,1)
        def choose():
            if directory:path=QFileDialog.getExistingDirectory(self,'选择'+title)
            else:path,_=QFileDialog.getOpenFileName(self,'选择'+title,'',filters)
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
        values.update(background_path=self.background_path.text().strip(),pip_path=self.pip_path.text().strip(),
            randomize=self.randomize.isChecked(),random_seed=self.random_seed.value(),
            random_ranges={key:[a.value(),b.value()] for key,(enabled,a,b) in self.range_widgets.items() if enabled.isChecked()},
            resource_pools={key:w.text().strip() for key,w in self.pool_widgets.items() if w.text().strip()})
        return values
