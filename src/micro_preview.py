"""In-app playback for disposable micro-innovation excerpts."""
from PySide6.QtCore import Qt, QUrl, QRect
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QWidget, QDialog, QVBoxLayout, QHBoxLayout, QSlider
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink
from shiboken6 import delete
from src.ui_design import label, btn


class PreviewSurface(QWidget):
    """Paint decoded frames inside Qt, including paused frames and mixed-DPI screens."""
    def __init__(self):
        super().__init__()
        self.frame = QImage()
        self.sink = QVideoSink(self)
        self.sink.videoFrameChanged.connect(self.show_frame)

    def show_frame(self, frame):
        if frame.isValid():
            self.frame = frame.toImage()
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.black)
        if not self.frame.isNull():
            size = self.frame.size().scaled(self.size(), Qt.KeepAspectRatio)
            target = QRect((self.width()-size.width())//2, (self.height()-size.height())//2,
                           size.width(), size.height())
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawImage(target, self.frame)


class MicroPreviewDialog(QDialog):
    def __init__(self, result, parent=None):
        super().__init__(parent)
        self.setWindowTitle('微创新效果预览')
        self.resize(850, 650)
        layout = QVBoxLayout(self)
        meta = result['metadata']
        layout.addWidget(label(f"当前设置 · 原片 {result['clip_start']:.2f} 秒起 · "
                               f"预览 {meta['duration']:.1f} 秒 · {meta['width']}×{meta['height']}"))
        self.video = PreviewSurface()
        self.video.setMinimumSize(240, 240)
        layout.addWidget(self.video, 1)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoSink(self.video.sink)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setAccessibleName('预览播放进度')
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.player.durationChanged.connect(lambda value: self.slider.setRange(0, value))
        self.player.positionChanged.connect(lambda value: self.slider.setValue(value)
                                            if not self.slider.isSliderDown() else None)
        layout.addWidget(self.slider)
        self.message = label('仅预览，不加入成品和上传列表。确认后可返回批量生成。')
        self.player.errorOccurred.connect(lambda error, text: self.message.setText('播放失败：' + text))
        layout.addWidget(self.message)
        row = QHBoxLayout()
        row.addWidget(btn('播放 / 暂停', self.toggle))
        row.addStretch()
        row.addWidget(btn('返回调整', self.reject))
        row.addWidget(btn('效果满意，保留设置', self.accept, True))
        layout.addLayout(row)
        self.player.setSource(QUrl.fromLocalFile(result['path']))

    def toggle(self):
        if self.player is None:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def done(self, result):
        if self.player is not None:
            self.player.stop()
            self.player.setSource(QUrl())
            # Stop the native decoder synchronously before removing its temporary file.
            delete(self.player)
            self.player = None
        super().done(result)
