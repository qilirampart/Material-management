from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QCursor, QDesktopServices, QPixmap, QWindow
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QPlainTextEdit,
    QFormLayout, QFileDialog, QComboBox, QGroupBox, QMessageBox, QSlider, QSplitter,
    QDialog, QScrollArea, QStackedWidget, QListWidget, QListWidgetItem,
)

from src.paths import RESOURCE_ROOT, DATA_ROOT
from src.browser_session import configure_persistent_profile, platform_browser_root
from src.edge_cdp import (
    edge_target_ids,
    evaluate_edge_page,
    find_page_ws_url,
    fit_new_edge_page,
    navigate_edge_page,
    set_edge_file_input,
)
from src.edge_session import (
    edge_window_bounds,
    find_embeddable_edge_window,
    focus_edge_window,
    launch_embedded_edge,
    prepare_edge_window_for_embedding,
    primary_mouse_button_pressed,
    release_edge_input,
)
from src.platform_bridge import (
    build_json_result_script,
    build_read_upload_selection_script,
    build_upload_file_input_script,
    build_upload_form_script,
    parse_json_result,
)
from src.upload import (
    build_upload_plan,
    eligible_materials,
    forget_upload_preference,
    load_upload_preferences,
    remember_upload_preferences,
    stage_upload_batch,
    suggested_drama_name,
    upload_preference_entries,
)
from src.vision import PHRASES, load_profile
from src.ui_design import Background, card, label


def button(text, callback, primary=False):
    widget = QPushButton(text)
    if primary:
        widget.setObjectName("primary")
    widget.clicked.connect(callback)
    return widget


def title(text):
    label = QLabel(text)
    label.setObjectName("heading")
    return label


def local_open(path):
    path = Path(path)
    if path.exists():
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))


class AspectRatioContainer(QWidget):
    def __init__(self, child=None, ratio=16 / 9, maximum_width=960, padding=16, parent=None):
        super().__init__(parent)
        self.ratio = ratio
        self.maximum_width = maximum_width
        self.padding = padding
        self.child = None
        self.setObjectName('browserStage')
        if child:
            self.set_widget(child)

    def set_widget(self, child):
        if self.child and self.child is not child:
            self.child.hide()
        self.child = child
        child.setParent(self)
        child.show()
        self._place_child()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_child()

    def _place_child(self):
        if not self.child or self.width() <= 0 or self.height() <= 0:
            return
        available_width = max(0, self.width() - self.padding * 2)
        available_height = max(0, self.height() - self.padding * 2)
        width = min(available_width, self.maximum_width)
        height = round(width / self.ratio)
        if height > available_height:
            height = available_height
            width = round(height * self.ratio)
        x = (self.width() - width) // 2
        y = (self.height() - height) // 2
        self.child.setGeometry(x, y, width, height)


class NativeWindowViewport(QWidget):
    def __init__(self, window, parent=None, left=8, top=38, right=8, bottom=8):
        super().__init__(parent)
        self.insets = (left, top, right, bottom)
        self.container = QWidget.createWindowContainer(window, self)
        self.container.setFocusPolicy(Qt.StrongFocus)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        left, top, right, bottom = self.insets
        self.container.setGeometry(
            -left,
            -top,
            self.width() + left + right,
            self.height() + top + bottom,
        )


class SettingsPage(QWidget):
    saved = Signal(dict)

    def __init__(self, config):
        super().__init__()
        self.config = dict(config)
        layout = QVBoxLayout(self)
        layout.addWidget(title("设置"))
        layout.addWidget(QLabel("配置在本机保存；检测规则更新后，已有素材需重新检测。"))
        form = QFormLayout()
        self.fields = {}
        items = [("output_root", "素材保存目录", True), ("model_config_path", "语言模型配置文件", False),
                 ("parser_config_path", "抖音解析配置文件", False), ("downloader_config_path", "下载参数文件", False),
                 ("logo_reference", "红果 logo 参考图", False)]
        for key, label, is_folder in items:
            value = self.config.get(key, "")
            if key == "logo_reference" and not Path(value).is_absolute():
                value = str(RESOURCE_ROOT / value)
            edit = QLineEdit(value)
            edit.setAccessibleName(label)
            self.fields[key] = edit
            row = QHBoxLayout()
            row.addWidget(edit)
            row.addWidget(button("浏览…", lambda checked=False, e=edit, d=is_folder: self.browse(e, d)))
            form.addRow(label, row)
        self.profiles = QComboBox()
        form.addRow("检测模型", self.profiles)
        form.addRow("", button("刷新模型列表", self.refresh_profiles))
        self.phrases = QPlainTextEdit("\n".join(config.get("phrases", PHRASES)))
        self.phrases.setMaximumHeight(110)
        self.phrases.setAccessibleName("禁用文字，每行一个")
        form.addRow("禁用文字（每行一个）", self.phrases)
        form.addRow("抽帧规则", QLabel("固定首帧 + 1 秒 + 2 秒；短视频自动调整"))
        self.website = QLineEdit(config.get("platform_url", ""))
        self.website.setPlaceholderText("公司平台地址，后续对齐；填写后可手动浏览")
        form.addRow("公司平台", self.website)
        layout.addLayout(form)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        layout.addWidget(button("保存设置", self.save, True), alignment=Qt.AlignLeft)
        layout.addStretch()
        self.refresh_profiles()

    def browse(self, edit, directory):
        path = QFileDialog.getExistingDirectory(self, "选择目录", edit.text()) if directory else QFileDialog.getOpenFileName(self, "选择文件", edit.text())[0]
        if path:
            edit.setText(path)
            if edit is self.fields["model_config_path"]:
                self.refresh_profiles()

    def refresh_profiles(self):
        self.profiles.clear()
        self.profiles.addItem("自动选择第一个可用模型", "")
        try:
            data = json.loads(Path(self.fields["model_config_path"].text()).read_text(encoding="utf-8-sig"))
            for profile in data.get("llm", {}).get("profiles", []):
                if profile.get("enabled", True):
                    self.profiles.addItem(f"{profile.get('name', '')} · {profile.get('model', '')}", profile.get("id", ""))
            index = self.profiles.findData(self.config.get("model_profile_id", ""))
            self.profiles.setCurrentIndex(max(0, index))
            self.message.setText("配置文件已读取。密钥不在界面或日志中展示。")
        except (OSError, ValueError, TypeError):
            self.message.setText("尚未读取到模型配置；请指定现有项目的 api_config.json。")

    def save(self):
        config = dict(self.config)
        config.update({key: edit.text().strip() for key, edit in self.fields.items()})
        config["model_profile_id"] = self.profiles.currentData()
        config["phrases"] = list(dict.fromkeys(line.strip() for line in self.phrases.toPlainText().splitlines() if line.strip()))
        config["platform_url"] = self.website.text().strip()
        if not config["phrases"] or not config["output_root"]:
            QMessageBox.warning(self, "设置不完整", "请填写保存目录和至少一个检测短语。")
            return
        if config["platform_url"]:
            url = QUrl(config["platform_url"])
            if not url.isValid() or url.scheme() not in ("https", "http") or not url.host() or url.userInfo():
                QMessageBox.warning(self, "网址无效", "请填写不含账号密码的 HTTP/HTTPS 平台地址。")
                return
        self.config = config
        self.saved.emit(config)
        self.message.setText("设置已保存。规则变化后可在任务页选择素材并重新检测。")


class ReviewPage(QWidget):
    note_saved = Signal(str, str, bool)
    recheck = Signal(str)
    picked = Signal(str)

    def __init__(self):
        super().__init__()
        self.video_id = ""
        self.path = ""
        self.blocked = False
        layout = QVBoxLayout(self)
        self.heading = title("检测复核")
        layout.addWidget(self.heading)
        self.caption = QLabel("在任务列表中双击一条素材，查看视频和检测证据。")
        layout.addWidget(self.caption)
        self.splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(self.splitter, 1)
        listing, listing_box = card('复核素材')
        self.materials = QListWidget()
        self.materials.setStyleSheet('QListWidget { border:0; background:white; } QListWidget::item { padding:15px 5px; border-bottom:1px solid #EDF1F2; } QListWidget::item:selected { background:#E5F3EF; color:#145951; }')
        self.materials.itemClicked.connect(lambda item: self.picked.emit(item.data(Qt.UserRole)))
        listing_box.addWidget(self.materials)
        self.splitter.addWidget(listing)
        left = QWidget()
        left.setObjectName('card')
        video_layout = QVBoxLayout(left)
        video_layout.setContentsMargins(16, 16, 16, 16)
        video_layout.addWidget(label('原始视频', 'section'))
        self.video = QVideoWidget()
        self.video.setMinimumSize(220, 240)
        self.poster = QLabel("尚未选择视频")
        self.poster.setAlignment(Qt.AlignCenter)
        self.poster.setMinimumSize(220, 200)
        self.poster.setStyleSheet("background: #182027; color: white;")
        self.poster_pixmap = QPixmap()
        self.video_stack = QStackedWidget()
        self.video_stack.addWidget(self.poster)
        self.video_stack.addWidget(self.video)
        video_layout.addWidget(self.video_stack, 1)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.playbackStateChanged.connect(self.playback_changed)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setAccessibleName("视频播放进度")
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.player.durationChanged.connect(lambda duration: self.slider.setRange(0, duration))
        self.player.positionChanged.connect(lambda value: self.slider.setValue(value) if not self.slider.isSliderDown() else None)
        video_layout.addWidget(self.slider)
        self.time = QLabel("00:00 / 00:00")
        self.player.positionChanged.connect(self.update_time)
        row = QHBoxLayout()
        self.play_button = button("播放 / 暂停", self.toggle_play)
        row.addWidget(self.play_button)
        row.addWidget(self.time)
        row.addStretch()
        video_layout.addLayout(row)
        video_layout.addWidget(label('片头抽帧', 'section'))
        self.frames_layout = QHBoxLayout()
        video_layout.addLayout(self.frames_layout)
        self.splitter.addWidget(left)
        right = QWidget()
        right.setObjectName("card")
        detail = QVBoxLayout(right)
        detail.setContentsMargins(16, 16, 16, 16)
        detail.addWidget(label('检测结论', 'section'))
        self.result = QLabel("尚未选择素材")
        self.result.setObjectName("section")
        detail.addWidget(self.result)
        detail.addWidget(QLabel("仅片头三帧，不代表全片审核通过"))
        self.evidence = QPlainTextEdit()
        self.evidence.setReadOnly(True)
        detail.addWidget(self.evidence, 1)
        detail.addWidget(QLabel("人工备注"))
        self.note = QPlainTextEdit()
        self.note.setMaximumHeight(85)
        detail.addWidget(self.note)
        actions = QHBoxLayout()
        actions.addWidget(button("保存备注", self.save_note))
        actions.addWidget(button("人工确认拦截", self.block))
        detail.addLayout(actions)
        actions2 = QHBoxLayout()
        actions2.addWidget(button("重新检测", lambda: self.recheck.emit(self.video_id) if self.video_id else None))
        actions2.addWidget(button("打开文件位置", lambda: local_open(Path(self.path).parent) if self.path else None))
        detail.addLayout(actions2)
        self.splitter.addWidget(right)
        self.splitter.setSizes([230, 480, 340])
        self.player.errorOccurred.connect(lambda error, text: self.caption.setText("播放器提示：" + text))

    def update_time(self, value):
        def formatted(ms):
            seconds = ms // 1000
            return f"{seconds // 60:02d}:{seconds % 60:02d}"
        self.time.setText(f"{formatted(value)} / {formatted(self.player.duration())}")

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def playback_changed(self, state):
        if state == QMediaPlayer.PlayingState:
            self.video_stack.setCurrentWidget(self.video)
        else:
            frame = self.video.videoSink().videoFrame()
            if frame.isValid():
                self.poster_pixmap = QPixmap.fromImage(frame.toImage())
            self.video_stack.setCurrentWidget(self.poster)
            self.resize_poster()

    def resize_poster(self):
        if not self.poster_pixmap.isNull():
            self.poster.setPixmap(self.poster_pixmap.scaled(self.poster.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resize_poster()

    def show_record(self, row, record, note, label):
        self.player.stop()
        self.video_id = row["video_id"]
        self.path = record.get("video_path", "")
        self.heading.setText("检测复核")
        self.caption.setText(str(row["source"]["剧名"] or "") + " · " + self.video_id)
        self.blocked = bool(note.get("blocked"))
        self.note.setPlainText(note.get("note", ""))
        self.result.setText(label)
        valid = bool(self.path) and Path(self.path).is_file()
        frames = record.get("frames", [])
        self.poster_pixmap = QPixmap(frames[0]["path"]) if frames else QPixmap()
        self.poster.clear()
        self.video_stack.setCurrentWidget(self.poster)
        self.resize_poster()
        self.player.setSource(QUrl.fromLocalFile(self.path) if valid else QUrl())
        self.play_button.setEnabled(valid)
        while self.frames_layout.count():
            item = self.frames_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for index, frame in enumerate(record.get("frames", []), 1):
            holder = QWidget()
            layout = QVBoxLayout(holder)
            layout.setContentsMargins(0, 0, 0, 0)
            from PySide6.QtGui import QIcon
            from PySide6.QtCore import QSize
            thumb = QPushButton()
            thumb.setIcon(QIcon(frame["path"]))
            thumb.setIconSize(QSize(90, 100))
            thumb.setAccessibleName(f"放大第{index}帧")
            if any(h.get('frame') == index for h in record.get('hits', [])):
                thumb.setStyleSheet('border:2px solid #CF5048;')
            thumb.clicked.connect(lambda checked=False, f=frame: self.enlarge(f))
            layout.addWidget(thumb)
            seek = button(f"{frame['seconds']:.3f} 秒", lambda checked=False, f=frame: self.player.setPosition(round(f["seconds"] * 1000)))
            layout.addWidget(seek)
            self.frames_layout.addWidget(holder)
        text = [record.get("reason", "")]
        for hit in record.get("hits", []):
            text.append(f"命中：{hit['match']} · 帧{hit['frame']}\n{hit['evidence']}")
        raw = record.get("raw", {})
        if isinstance(raw, dict):
            for frame in raw.get("frames", []):
                logo = {"absent": "未发现", "present": "命中", "uncertain": "待复核"}.get(frame.get("logo"), "未知")
                text.append(f"\n帧 {frame.get('index')} 识别原文\n{frame.get('text', '')}\n红果图标：{logo} {frame.get('logo_evidence', '')}")
        if record.get("model"):
            text.append("\n检测模型：" + record["model"])
        self.evidence.setPlainText("\n".join(text).strip() or "尚无检测结果。")

    def enlarge(self, frame):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"证据帧 · {frame['seconds']:.3f} 秒")
        layout = QVBoxLayout(dialog)
        label = QLabel()
        pixmap = QPixmap(frame["path"])
        label.setPixmap(pixmap.scaled(700, 720, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(label)
        dialog.exec()

    def save_note(self):
        if self.video_id:
            self.note_saved.emit(self.video_id, self.note.toPlainText(), self.blocked)

    def block(self):
        if not self.video_id:
            return
        if not self.note.toPlainText().strip():
            QMessageBox.information(self, "记录原因", "请先在人工备注中填写拦截原因。")
            return
        self.blocked = True
        self.result.setText("人工确认拦截 · 不上传")
        self.save_note()


class UploadConfigDialog(QDialog):
    submitted = Signal()

    def __init__(self, uploader_initials='', parent=None):
        super().__init__(parent)
        self.setWindowTitle('配置上传批次')
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        layout.addWidget(label('上传信息', 'section'))
        layout.addWidget(label('剧名由需求表预填；同一剧名可保留多个平台短剧 ID。'))
        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        self.history = QComboBox()
        self.delete_history_button = QPushButton('删除当前记录')
        history_row = QHBoxLayout()
        history_row.addWidget(self.history, 1)
        history_row.addWidget(self.delete_history_button)
        self.director = QLineEdit()
        self.director.setPlaceholderText('选择或填写编导')
        self.drama_name = QLineEdit()
        self.drama_name.setPlaceholderText('从导入表格的剧名预填')
        self.drama_id = QComboBox()
        self.drama_id.setEditable(True)
        self.drama_id.lineEdit().setPlaceholderText('平台建议短剧 ID')
        self.uploader_initials = QLineEdit(uploader_initials)
        self.uploader_initials.setPlaceholderText('例如 ZYY')
        form.addRow('历史配置', history_row)
        form.addRow('编导', self.director)
        form.addRow('建议短剧', self.drama_name)
        form.addRow('短剧 ID', self.drama_id)
        form.addRow('上传人缩写', self.uploader_initials)
        layout.addLayout(form)
        self.message = label('生成后将按每批最多 50 条准备上传文件。')
        layout.addWidget(self.message)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(button('取消', self.reject))
        self.generate_button = button('生成上传批次', lambda: self.submitted.emit(), True)
        actions.addWidget(self.generate_button)
        layout.addLayout(actions)


class PlatformPage(QWidget):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.browser = None
        self.materials = []
        self.batch_folder = None
        self.upload_batches = []
        self.staging_task = None
        self.edge_profile = None
        self.edge_previous_windows = set()
        self.edge_attach_attempt = 0
        self.edge_foreign_window = None
        self.edge_container = None
        self.edge_window_handle = None
        self.edge_previous_targets = set()
        self.edge_target_ws_url = None
        try:
            self.internal_browser_debug_port = int(
                os.environ.get(
                    'QTWEBENGINE_REMOTE_DEBUGGING',
                    config.get('internal_browser_debug_port', 9233),
                )
            )
        except (TypeError, ValueError):
            self.internal_browser_debug_port = 9233
        self.edge_zoom_task = None
        self.edge_navigation_task = None
        self.edge_focus_timer = QTimer(self)
        self.edge_focus_timer.setInterval(15)
        self.edge_focus_timer.timeout.connect(self._sync_edge_input_focus)
        QApplication.instance().focusChanged.connect(self._release_edge_focus_for_widget)
        self.preferences_path = Path(config.get('upload_preferences_path', DATA_ROOT / 'runtime' / 'upload-preferences.json'))
        self.upload_preferences = load_upload_preferences(self.preferences_path)
        self.upload_config_dialog = UploadConfigDialog(self.upload_preferences['uploader_initials'], self)
        self.upload_config_dialog.submitted.connect(self.prepare_upload)
        self.upload_config_dialog.history.currentIndexChanged.connect(self.apply_upload_history)
        self.upload_config_dialog.delete_history_button.clicked.connect(self.delete_upload_history)
        self.director = self.upload_config_dialog.director
        self.drama_name = self.upload_config_dialog.drama_name
        self.drama_id = self.upload_config_dialog.drama_id
        self.uploader_initials = self.upload_config_dialog.uploader_initials
        self.drama_id.currentTextChanged.connect(self.apply_remembered_director)
        self.prepare_button = self.upload_config_dialog.generate_button
        self.refresh_upload_history()
        layout = QVBoxLayout(self)
        layout.addWidget(title('平台工作台'))
        layout.addWidget(label('在软件内登录公司平台，准备并上传检测通过的素材'))
        body = QHBoxLayout()
        browser_card, box = card()
        row = QHBoxLayout()
        self.back_button = button('←', lambda: self.navigate_platform('back'))
        self.forward_button = button('→', lambda: self.navigate_platform('forward'))
        self.reload_button = button('刷新', lambda: self.navigate_platform('reload'))
        row.addWidget(self.back_button)
        row.addWidget(self.forward_button)
        row.addWidget(self.reload_button)
        self.address = QLineEdit(config.get('platform_url', ''))
        self.address.setPlaceholderText('请输入公司平台地址')
        self.address.returnPressed.connect(self.open_platform)
        row.addWidget(self.address, 1)
        developer_mode = bool(config.get('developer_edge_mode', False))
        self.edge_button = button('打开已登录 Edge', self.open_edge_session)
        self.edge_button.setVisible(developer_mode)
        row.addWidget(self.edge_button)
        self.internal_browser_button = button(
            '新建登录' if developer_mode else '打开平台',
            self.open_platform,
            True,
        )
        row.addWidget(self.internal_browser_button)
        box.addLayout(row)
        self.area = QVBoxLayout()
        self.empty = QLabel('▣\n\n打开公司素材平台\n\n首次使用请填写平台地址，打开后由您自行登录。\n\n登录状态保存在本机，平台要求重新验证时请再次登录。')
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setObjectName('platformEmpty')
        self.browser_stage = AspectRatioContainer(self.empty)
        self.area.addWidget(self.browser_stage, 1)
        box.addLayout(self.area, 1)
        self.status = label('尚未打开平台 · 浏览模式')
        box.addWidget(self.status)
        body.addWidget(browser_card, 1)
        preparation, box = card('上传准备')
        preparation.setMaximumWidth(340)
        box.addWidget(label('当前勾选', 'section'))
        self.material_summary = label('0 条可上传 · 请在素材任务中勾选')
        box.addWidget(self.material_summary)
        self.material_list = QListWidget()
        self.material_list.setMaximumHeight(120)
        self.material_list.setAlternatingRowColors(True)
        box.addWidget(self.material_list)
        box.addWidget(label('固定信息', 'section'))
        box.addWidget(label('视频 · 原创 · 张雯燕 · 短剧\n产品不限 · 付费 · 按部门可见'))
        self.read_selection_button = button('读取平台已选信息', self.read_platform_selection)
        self.read_selection_button.setEnabled(False)
        box.addWidget(self.read_selection_button)
        self.configure_button = button('配置上传信息', self.open_upload_config, True)
        self.configure_button.setEnabled(False)
        box.addWidget(self.configure_button)
        self.prepare_button.setEnabled(False)
        self.batch_selector = QComboBox()
        self.batch_selector.setEnabled(False)
        self.batch_selector.setVisible(False)
        box.addWidget(self.batch_selector)
        self.preview = label('尚未生成上传文件名')
        self.preview.setWordWrap(True)
        box.addWidget(self.preview)
        box.addStretch()
        self.fill_button = button('填写平台并选择文件', self.fill_platform_form, True)
        self.fill_button.setEnabled(False)
        box.addWidget(self.fill_button)
        box.addWidget(label('只完成文件选择与页面填写，不保存草稿，不提交审核。'))
        body.addWidget(preparation)
        layout.addLayout(body, 1)

    def navigate_platform(self, action):
        if self.browser:
            {
                'back': self.browser.back,
                'forward': self.browser.forward,
                'reload': self.browser.reload,
            }[action]()
            return
        if not self.edge_target_ws_url:
            self.status.setText('\u8bf7\u5148\u6253\u5f00\u5e73\u53f0')
            return
        self._set_navigation_enabled(False)
        self.status.setText({
            'back': '\u6b63\u5728\u8fd4\u56de\u4e0a\u4e00\u9875\u2026',
            'forward': '\u6b63\u5728\u524d\u5f80\u4e0b\u4e00\u9875\u2026',
            'reload': '\u6b63\u5728\u5237\u65b0\u5e73\u53f0\u9875\u9762\u2026',
        }[action])
        self.edge_navigation_task = Background(
            lambda: navigate_edge_page(self.edge_target_ws_url, action),
            self,
        )
        self.edge_navigation_task.result.connect(self._edge_navigation_finished)
        self.edge_navigation_task.failed.connect(self._edge_navigation_failed)
        self.edge_navigation_task.finished.connect(lambda: self._set_navigation_enabled(True))
        self.edge_navigation_task.start()

    def _set_navigation_enabled(self, enabled):
        self.back_button.setEnabled(enabled)
        self.forward_button.setEnabled(enabled)
        self.reload_button.setEnabled(enabled)

    def _edge_navigation_finished(self, result):
        result = result if isinstance(result, dict) else {}
        if result.get('url'):
            self.address.setText(str(result['url']))
        if not result.get('ok'):
            self.status.setText(result.get('message', '\u65e0\u6cd5\u5207\u6362\u5e73\u53f0\u9875\u9762'))
            return
        action_text = {
            'back': '\u5df2\u8fd4\u56de\u4e0a\u4e00\u9875',
            'forward': '\u5df2\u524d\u5f80\u4e0b\u4e00\u9875',
            'reload': '\u5e73\u53f0\u9875\u9762\u5df2\u5237\u65b0',
        }
        self.status.setText(action_text.get(result.get('action'), '\u5e73\u53f0\u9875\u9762\u5df2\u66f4\u65b0'))

    def _edge_navigation_failed(self, message):
        self.status.setText(f'\u5e73\u53f0\u9875\u9762\u64cd\u4f5c\u5931\u8d25\uff1a{message}')

    def open_edge_session(self):
        if self.edge_container is not None:
            self.edge_container.setFocus()
            return
        self.edge_button.setEnabled(False)
        self.status.setText('正在启动并嵌入已登录 Edge…')
        try:
            port = int(self.config.get('edge_debug_port', 9222))
            try:
                self.edge_previous_targets = edge_target_ids(port)
            except OSError:
                self.edge_previous_targets = set()
            self.edge_profile, self.edge_previous_windows = launch_embedded_edge(
                self.address.text(), self.config
            )
        except Exception as exc:
            self.edge_button.setEnabled(True)
            self.status.setText('打开已登录 Edge 失败')
            QMessageBox.information(self, '无法打开 Edge', str(exc))
            return
        self.edge_attach_attempt = 0
        QTimer.singleShot(250, self._attach_edge_session)

    def _attach_edge_session(self):
        handle = find_embeddable_edge_window(self.edge_previous_windows)
        if handle:
            self.edge_foreign_window = QWindow.fromWinId(handle)
            if self.edge_foreign_window:
                self.edge_window_handle = handle
                self.edge_container = NativeWindowViewport(self.edge_foreign_window, self)
                self.edge_container.setFocusPolicy(Qt.StrongFocus)
                self.browser_stage.set_widget(self.edge_container)
                prepare_edge_window_for_embedding(handle)
                QTimer.singleShot(100, lambda: prepare_edge_window_for_embedding(handle))
                QTimer.singleShot(150, lambda: focus_edge_window(handle))
                self.status.setText('已嵌入专用 Edge · 正在适配页面尺寸…')
                QTimer.singleShot(1200, self._fit_edge_session)
                self.edge_button.setEnabled(False)
                self.edge_focus_timer.start()
                return
        self.edge_attach_attempt += 1
        if self.edge_attach_attempt < 40:
            QTimer.singleShot(250, self._attach_edge_session)
        else:
            self.edge_button.setEnabled(True)
            self.status.setText('Edge 已启动，但未找到可嵌入窗口，请重试。')

    def _fit_edge_session(self):
        port = int(self.config.get('edge_debug_port', 9222))
        expected_bounds = edge_window_bounds(self.edge_window_handle)
        self.edge_zoom_task = Background(
            lambda: fit_new_edge_page(
                self.edge_previous_targets,
                self.address.text().strip(),
                port,
                0.67,
                expected_bounds=expected_bounds,
            ),
            self,
        )
        self.edge_zoom_task.result.connect(self._edge_session_ready)
        self.edge_zoom_task.failed.connect(self._edge_session_fit_failed)
        self.edge_zoom_task.start()

    def _edge_session_ready(self, ws_url):
        self.edge_target_ws_url = ws_url
        self.read_selection_button.setEnabled(True)
        if self.edge_window_handle:
            prepare_edge_window_for_embedding(self.edge_window_handle)
            QTimer.singleShot(
                100,
                lambda: prepare_edge_window_for_embedding(self.edge_window_handle),
            )
            QTimer.singleShot(
                500,
                lambda: prepare_edge_window_for_embedding(self.edge_window_handle),
            )
        self.status.setText(f'已嵌入专用 Edge · 登录状态保存在 {self.edge_profile}')

    def _edge_session_fit_failed(self, message):
        self.status.setText(f'Edge 已嵌入 · 页面尺寸自动适配失败：{message}')

    def _sync_edge_input_focus(self):
        if not self.edge_window_handle or not self.edge_container or not self.edge_container.isVisible():
            return
        if QApplication.activeModalWidget() is not None:
            return
        local_cursor = self.edge_container.mapFromGlobal(QCursor.pos())
        mouse_pressed = (
            QApplication.mouseButtons() & Qt.LeftButton
            or primary_mouse_button_pressed()
        )
        if self.edge_container.rect().contains(local_cursor) and mouse_pressed:
            focus_edge_window(self.edge_window_handle)

    def _release_edge_focus_for_widget(self, _old, current):
        if not self.edge_window_handle or current is None or self.edge_container is None:
            return
        if current is not self.edge_container and not self.edge_container.isAncestorOf(current):
            release_edge_input(self.edge_window_handle)

    def closeEvent(self, event):
        if self.edge_window_handle:
            release_edge_input(self.edge_window_handle)
        super().closeEvent(event)

    def set_materials(self, rows, records, notes, selected_ids, batch_folder):
        self.materials = eligible_materials(rows, records, notes, selected_ids)
        self.batch_folder = Path(batch_folder) if batch_folder else None
        self.upload_batches = []
        self.batch_selector.clear()
        self.batch_selector.setEnabled(False)
        self.batch_selector.setVisible(False)
        self.fill_button.setEnabled(False)
        self.material_list.clear()
        for material in self.materials:
            drama = str(material.get('source', {}).get('剧名', '')).strip() or '未命名素材'
            self.material_list.addItem(f"{drama} · {material['video_id']}")
        self.material_summary.setText(f'{len(self.materials)} 条可上传 · 仅包含当前勾选且检测通过的素材')
        proposed = suggested_drama_name(self.materials)
        self.refresh_upload_history()
        if proposed:
            self.drama_name.setText(proposed)
            remembered = self.upload_preferences['dramas'].get(proposed, {})
            self.drama_id.blockSignals(True)
            self.drama_id.clear()
            self.drama_id.addItems(remembered.get('ids', {}).keys())
            self.drama_id.setCurrentIndex(-1)
            self.drama_id.blockSignals(False)
            self.director.clear()
        else:
            self.drama_name.clear()
            self.drama_id.clear()
            self.director.clear()
        self.prepare_button.setEnabled(bool(self.materials and self.batch_folder))
        self.configure_button.setEnabled(bool(self.materials and self.batch_folder))
        self.preview.setText('填写上传信息后生成批次' if self.materials else '没有符合条件的勾选素材')

    def open_upload_config(self):
        if not self.materials:
            return
        if self.edge_window_handle:
            release_edge_input(self.edge_window_handle)
        self.upload_config_dialog.message.setText('生成后将按每批最多 50 条准备上传文件。')
        self.upload_config_dialog.exec()

    def read_platform_selection(self):
        script = build_read_upload_selection_script()
        self.read_selection_button.setEnabled(False)
        self.status.setText('正在读取平台当前选择…')
        if self.browser:
            self.browser.page().runJavaScript(
                build_json_result_script(script),
                lambda result: self._platform_selection_finished(parse_json_result(result)),
            )
            return
        if self.edge_target_ws_url:
            self.selection_task = Background(
                lambda: evaluate_edge_page(self.edge_target_ws_url, script),
                self,
            )
            self.selection_task.result.connect(self._platform_selection_finished)
            self.selection_task.failed.connect(self._platform_selection_failed)
            self.selection_task.start()
            return
        self.read_selection_button.setEnabled(True)
        QMessageBox.information(self, '尚未打开平台', '请先打开公司平台并进入添加素材页面。')

    def _platform_selection_finished(self, result):
        self.read_selection_button.setEnabled(True)
        result = result if isinstance(result, dict) else {}
        if not result.get('ok'):
            self.status.setText(result.get('message', '未读取到平台选择'))
            return
        self.director.setText(str(result.get('director', '')).strip())
        self.drama_name.setText(str(result.get('dramaName', '')).strip())
        self.drama_id.setEditText(str(result.get('dramaId', '')).strip())
        remember_upload_preferences(
            self.preferences_path,
            drama_name=self.drama_name.text(),
            drama_platform_id=self.drama_id.currentText(),
            director=self.director.text(),
            uploader_initials=self.uploader_initials.text(),
        )
        self.upload_preferences = load_upload_preferences(self.preferences_path)
        self.refresh_upload_history((self.drama_name.text(), self.drama_id.currentText()))
        self.status.setText(
            f"已读取并保存：{self.director.text()} · {self.drama_id.currentText()}-{self.drama_name.text()}"
        )

    def _platform_selection_failed(self, message):
        self.read_selection_button.setEnabled(True)
        self.status.setText(f'读取平台选择失败：{message}')

    def refresh_upload_history(self, preferred=None):
        history = self.upload_config_dialog.history
        history.blockSignals(True)
        history.clear()
        history.addItem('请选择历史配置', None)
        selected_index = 0
        for entry in upload_preference_entries(self.upload_preferences):
            text = f"{entry['drama_platform_id']}-{entry['drama_name']} · {entry['director']}"
            history.addItem(text, entry)
            if preferred == (entry['drama_name'], entry['drama_platform_id']):
                selected_index = history.count() - 1
        history.setCurrentIndex(selected_index)
        history.blockSignals(False)

    def apply_upload_history(self, _index):
        entry = self.upload_config_dialog.history.currentData()
        if not isinstance(entry, dict):
            return
        self.director.setText(entry['director'])
        self.drama_name.setText(entry['drama_name'])
        self.drama_id.setEditText(entry['drama_platform_id'])

    def delete_upload_history(self):
        entry = self.upload_config_dialog.history.currentData()
        if not isinstance(entry, dict):
            return
        answer = QMessageBox.question(
            self.upload_config_dialog,
            '删除历史配置',
            f"确定删除 {entry['drama_platform_id']}-{entry['drama_name']} · {entry['director']}？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        forget_upload_preference(
            self.preferences_path,
            entry['drama_name'],
            entry['drama_platform_id'],
        )
        if (
            self.drama_name.text().strip() == entry['drama_name']
            and self.drama_id.currentText().strip() == entry['drama_platform_id']
        ):
            self.drama_id.setCurrentIndex(-1)
            self.director.clear()
        self.upload_preferences = load_upload_preferences(self.preferences_path)
        self.refresh_upload_history()

    def prepare_upload(self):
        try:
            plan = build_upload_plan(
                self.materials,
                drama_name=self.drama_name.text(),
                drama_platform_id=self.drama_id.currentText(),
                director=self.director.text(),
                uploader_initials=self.uploader_initials.text(),
            )
            staging = self.batch_folder / 'upload-staging'
            remember_upload_preferences(
                self.preferences_path,
                drama_name=self.drama_name.text(),
                drama_platform_id=self.drama_id.currentText(),
                director=self.director.text(),
                uploader_initials=self.uploader_initials.text(),
            )
            self.upload_preferences = load_upload_preferences(self.preferences_path)
        except (OSError, ValueError, KeyError) as exc:
            self.preview.setText(str(exc))
            self.upload_config_dialog.message.setText(str(exc))
            self.fill_button.setEnabled(False)
            return
        self.upload_config_dialog.accept()
        self.prepare_button.setEnabled(False)
        self.fill_button.setEnabled(False)
        self.preview.setText('正在后台生成上传暂存文件…')
        self.staging_task = Background(lambda: [stage_upload_batch(batch, staging) for batch in plan], self)
        self.staging_task.result.connect(self.staging_ready)
        self.staging_task.failed.connect(self.staging_failed)
        self.staging_task.start()

    def apply_remembered_director(self, platform_id):
        drama = self.upload_preferences['dramas'].get(self.drama_name.text().strip(), {})
        remembered = drama.get('ids', {}).get(platform_id, {})
        if remembered.get('director'):
            self.director.setText(remembered['director'])

    def staging_ready(self, batches):
        self.upload_batches = batches
        self.batch_selector.clear()
        for batch in self.upload_batches:
            self.batch_selector.addItem(f"第 {batch['index']} 批 · {len(batch['items'])} 条", batch['index'] - 1)
        self.batch_selector.setEnabled(bool(self.upload_batches))
        self.batch_selector.setVisible(bool(self.upload_batches))
        self.fill_button.setEnabled(bool(self.upload_batches))
        first = self.upload_batches[0]['items'][0]['upload_name'] if self.upload_batches else ''
        self.preview.setText(f'已生成 {len(self.upload_batches)} 个批次\n文件名示例：{first}')
        self.prepare_button.setEnabled(bool(self.materials and self.batch_folder))

    def staging_failed(self, message):
        self.upload_batches = []
        self.preview.setText(message)
        self.prepare_button.setEnabled(bool(self.materials and self.batch_folder))
        self.fill_button.setEnabled(False)

    def fill_platform_form(self):
        if not self.browser and not self.edge_target_ws_url:
            QMessageBox.information(self, '尚未打开平台', '请先打开公司平台并完成扫码登录。')
            return
        if not self.upload_batches:
            return
        batch = self.upload_batches[self.batch_selector.currentData() or 0]
        paths = [item['upload_path'] for item in batch['items']]
        if not all(Path(path).is_file() for path in paths):
            self.status.setText('上传暂存文件缺失，请重新生成批次')
            return
        self.fill_button.setEnabled(False)
        self.status.setText(f"正在填写第 {batch['index']} 批 · {len(paths)} 条")
        self._run_platform_fill(batch, 0)

    def _run_platform_fill(self, batch, attempt):
        script = build_upload_form_script(
            director=self.director.text(),
            drama_name=self.drama_name.text(),
            drama_platform_id=self.drama_id.currentText(),
            file_count=len(batch['items']),
            request_file_dialog=False,
        )
        if self.browser:
            self.browser.page().runJavaScript(
                build_json_result_script(script),
                lambda result: self._platform_fill_finished(
                    batch, attempt, parse_json_result(result)
                ),
            )
            return
        self.edge_fill_task = Background(
            lambda: evaluate_edge_page(self.edge_target_ws_url, script),
            self,
        )
        self.edge_fill_task.result.connect(
            lambda result: self._platform_fill_finished(batch, attempt, result)
        )
        self.edge_fill_task.failed.connect(self._edge_files_failed)
        self.edge_fill_task.start()

    def _platform_fill_finished(self, batch, attempt, result):
        result = result if isinstance(result, dict) else {}
        if result.get('code') in {'OPENING_FORM', 'SOURCE_TYPE_CHANGING', 'BOOK_SEARCH_STARTED'} and attempt < 5:
            if result.get('code') == 'BOOK_SEARCH_STARTED':
                self.status.setText('正在使用平台搜索并选择建议短剧…')
                delay = 1800
            elif result.get('code') == 'SOURCE_TYPE_CHANGING':
                self.status.setText('正在切换为视频素材并等待表单刷新…')
                delay = 1000
            else:
                self.status.setText('已打开上传表单，等待页面控件加载…')
                delay = 800
            QTimer.singleShot(delay, lambda: self._run_platform_fill(batch, attempt + 1))
            return
        if result.get('ok') and result.get('code') == 'FILE_INPUT_READY' and (self.browser or self.edge_target_ws_url):
            paths = [item['upload_path'] for item in batch['items']]
            self.status.setText('页面字段已填写，正在选择视频文件…')
            if self.browser:
                platform_url = str(self.config.get('platform_url', self.address.text())).strip()
                ws_url = lambda: find_page_ws_url(
                    platform_url,
                    self.internal_browser_debug_port,
                )
            else:
                ws_url = lambda: self.edge_target_ws_url
            self.edge_files_task = Background(
                lambda: set_edge_file_input(
                    ws_url(),
                    build_upload_file_input_script(),
                    paths,
                ),
                self,
            )
            self.edge_files_task.result.connect(self._edge_files_selected)
            self.edge_files_task.failed.connect(self._edge_files_failed)
            self.edge_files_task.start()
            return
        self.fill_button.setEnabled(True)
        if result.get('ok'):
            self.status.setText(result.get('message', '平台表单已填写'))
            self.preview.setText(self.preview.text() + '\n已交给网页文件选择器；未保存草稿，未提交审核。')
        else:
            self.status.setText(result.get('message', '页面填写失败，请确认已经登录并进入素材管理'))

    def _edge_files_selected(self, result):
        self.fill_button.setEnabled(True)
        result = result if isinstance(result, dict) else {}
        count = int(result.get('plugin_count') or result.get('input_count') or 0)
        preview_count = int(result.get('video_preview_count') or result.get('preview_count') or count)
        names = [str(name) for name in result.get('names', [])]
        visible_name = names[0] if names else '未返回文件名'
        more = f' 等 {count} 个文件' if count > 1 else ''
        self.status.setText(f'平台已接收 {count} 个文件并显示 {preview_count} 个视频预览：{visible_name}{more}')
        self.preview.setText(
            self.preview.text()
            + f'\n平台已显示 {preview_count} 个视频预览：{visible_name}{more}；未保存草稿，未提交审核。'
        )

    def _edge_files_failed(self, message):
        self.fill_button.setEnabled(True)
        self.status.setText(f'平台填写失败：{message}')

    def open_platform(self):
        url = QUrl(self.address.text().strip())
        if not url.isValid() or url.scheme() not in ("http", "https") or not url.host() or url.userInfo():
            QMessageBox.information(self, "平台地址待配置", "请在设置中填写公司平台地址。")
            return
        if self.browser is None:
            os.environ.setdefault(
                'QTWEBENGINE_REMOTE_DEBUGGING',
                str(self.internal_browser_debug_port),
            )
            from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
            from PySide6.QtWebEngineWidgets import QWebEngineView

            self.profile = QWebEngineProfile("company-platform", self)
            folder = platform_browser_root(self.config)
            configure_persistent_profile(self.profile, folder)
            self.browser = QWebEngineView(self)
            self.upload_page = QWebEnginePage(self.profile, self.browser)
            self.browser.setPage(self.upload_page)
            self.browser.setZoomFactor(0.67)
            self.browser.loadFinished.connect(self._platform_load_finished)
            self.browser.urlChanged.connect(lambda target: self.address.setText(target.toDisplayString()))
            self.browser_stage.set_widget(self.browser)
        self.status.setText("正在打开公司平台…")
        self.browser.setUrl(url)

    def _platform_load_finished(self, ok):
        self.read_selection_button.setEnabled(bool(ok))
        self.status.setText("页面已加载 · 可读取添加素材页当前选择" if ok else "网页加载失败，请检查内网连接与平台地址")
