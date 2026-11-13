"""Compact working-copy editor for optional grid and canvas effects."""
from types import SimpleNamespace
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QComboBox,
    QSpinBox,QDoubleSpinBox,QLineEdit)
from src.ui_design import btn,label
from src.variant_dialog import VariantDialog
from src.picture_effects import PICTURE_DEFAULTS,validate_picture_effects


class PictureEffectsDialog(QDialog):
    def __init__(self,values,parent=None):
        super().__init__(parent)
        self.setWindowTitle('分屏与画面效果');self.resize(620,530)
        self.settings={k:values.get(k,v) for k,v in PICTURE_DEFAULTS.items()}
        outer=QVBoxLayout(self);outer.addWidget(label('分屏与画面效果','heading'))
        outer.addWidget(label('复制同一原片排布，再应用画布设置；保留一条原声，不重排剧情。'))
        form=QFormLayout();form.setSpacing(12);outer.addLayout(form)
        self.layout_choice=QComboBox()
        for text,value in [('不分屏','none'),('上下两屏','two_rows'),('上下三屏','three_rows'),
                ('左右两屏','two_columns'),('左右三屏','three_columns'),('四宫格','quad')]:self.layout_choice.addItem(text,value)
        form.addRow('分屏布局',self.layout_choice)
        self.fit=QComboBox();self.fit.addItem('完整显示，留黑边','contain');self.fit.addItem('铺满单格，裁掉边缘','fill')
        form.addRow('单格适配',self.fit)
        self.layout_choice.currentIndexChanged.connect(lambda:self.fit.setEnabled(self.layout_choice.currentData()!='none'))
        self.style=QComboBox()
        for text,value in [('保留原色','original'),('黑白','monochrome'),('底片反色','negative'),('复古棕褐','sepia')]:self.style.addItem(text,value)
        form.addRow('画面风格',self.style)
        self.vignette=QDoubleSpinBox();self.vignette.setRange(0,100);self.vignette.setDecimals(0)
        self.vignette.setSuffix(' %');self.vignette.setSingleStep(5);self.vignette.setKeyboardTracking(False)
        form.addRow('暗角强度',VariantDialog._stepper(self.vignette,'暗角强度'))
        self.width=QSpinBox();self.width.setRange(0,40);self.width.setSuffix(' px');self.width.setKeyboardTracking(False)
        form.addRow('外框宽度',VariantDialog._stepper(self.width,'外框宽度'))
        self.color=QLineEdit();self.color.setMaxLength(6);form.addRow('外框颜色',self.color)
        outer.addWidget(label('0 表示关闭。效果作用于主体画布；叠片、文字、水印在其上方，片头尾和封面不受影响。'))
        outer.addWidget(label('分屏可能缩小字幕；铺满会裁边，请先预览。外框向内绘制，不改变输出尺寸。'))
        self.status=label('');outer.addWidget(self.status);outer.addStretch()
        actions=QHBoxLayout();actions.addWidget(btn('关闭本组效果',self.reset));actions.addStretch()
        actions.addWidget(btn('取消',self.reject));actions.addWidget(btn('保留设置',self.save,True));outer.addLayout(actions)
        self.apply(self.settings)

    def apply(self,values):
        for widget,key in ((self.layout_choice,'grid_layout'),(self.fit,'grid_fit'),(self.style,'picture_style')):
            widget.setCurrentIndex(widget.findData(values[key]))
        self.fit.setEnabled(self.layout_choice.currentData()!='none')
        self.width.setValue(values['border_width']);self.color.setText(values['border_color'])
        self.vignette.setValue(values['vignette']*100)

    def reset(self):self.apply(PICTURE_DEFAULTS);self.status.setText('已关闭本组效果；点击保留设置后生效。')

    def save(self):
        values=dict(grid_layout=self.layout_choice.currentData(),grid_fit=self.fit.currentData(),
            picture_style=self.style.currentData(),vignette=self.vignette.value()/100,
            border_width=self.width.value(),border_color=self.color.text().strip())
        try:validate_picture_effects(SimpleNamespace(**values))
        except ValueError as exc:self.status.setText(str(exc));return
        self.settings=values;self.accept()
