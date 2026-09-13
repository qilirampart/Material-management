"""Shared native desktop components and settings; no web UI server."""
import json
import sys
import uuid
import copy
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QProcess, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFormLayout, QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QCheckBox,
    QFileDialog, QMessageBox, QGridLayout, QDialog, QScrollArea)
from src.paths import DATA_ROOT, RESOURCE_ROOT
from src.update import APP_VERSION, REPOSITORY, check_for_update, download_update
from src.vision import PHRASES, image_part

STYLE = """
QMainWindow { background:#F4F6F8; }
QWidget { color:#193941; font-family:'Microsoft YaHei'; font-size:13px; }
QWidget#rail, QListWidget#navigation { background:#103E46; color:#D6E8E7; border:0; }
QLabel#brand { color:white; font-size:19px; font-weight:700; padding:22px 16px; }
QListWidget#navigation { padding:10px; }
QListWidget#navigation::item { padding:16px 10px; margin:5px 0; border-radius:7px; }
QListWidget#navigation::item:selected { background:#1A6E70; color:white; }
QLabel#heading { font-size:25px; font-weight:700; padding:2px 0 8px; }
QLabel#section { font-size:17px; font-weight:600; padding:2px 0 8px; }
QLabel#muted { color:#76858B; }
QWidget#card { background:white; border:1px solid #DCE5E7; border-radius:10px; }
QWidget#card QLabel { background:transparent; }
QPushButton { background:white; border:1px solid #CCD8DC; border-radius:5px; padding:8px 12px; min-height:18px; }
QPushButton:hover { background:#E8F4F2; border-color:#78AAA8; }
QPushButton:disabled { color:#95A0A5; background:#EEF1F3; }
QPushButton#primary { background:#0F766E; color:white; border-color:#0F766E; }
QPushButton#primary:disabled { background:#9EBFBA; border-color:#9EBFBA; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox { background:white; border:1px solid #D7E0E4; border-radius:5px; padding:7px; selection-background-color:#D2EAE5; }
QTableWidget { background:white; alternate-background-color:#FAFCFC; border:0; gridline-color:#EBF0F2; selection-background-color:#E6F3F0; selection-color:#143F3B; }
QHeaderView::section { background:#F4F7F8; color:#53676F; border:0; padding:10px 6px; }
QTableWidget::indicator, QCheckBox::indicator { width:17px; height:17px; }
QTableWidget::indicator:unchecked, QCheckBox::indicator:unchecked { background:white; border:1px solid #A9B9BE; border-radius:3px; }
QTableWidget::indicator:checked, QCheckBox::indicator:checked { background:#0F766E; border:1px solid #0F766E; border-radius:3px; }
QScrollArea { border:0; background:transparent; }
QStatusBar { background:white; border-top:1px solid #DFE7E9; color:#6D7D84; }
QLabel#summary { color:#526970; padding:5px 0; }
QWidget#browserStage { background:#EDF2F3; border-radius:7px; }
QLabel#platformEmpty { color:#72828A; font-size:16px; background:white; border:1px solid #DCE5E7; }
"""


def btn(text, callback, primary=False):
    b = QPushButton(text)
    if primary:
        b.setObjectName('primary')
    b.clicked.connect(callback)
    return b


def label(text, kind='muted'):
    w = QLabel(text)
    w.setObjectName(kind)
    w.setWordWrap(True)
    return w


def card(heading=''):
    w = QWidget()
    w.setObjectName('card')
    box = QVBoxLayout(w)
    box.setContentsMargins(18, 16, 18, 16)
    box.setSpacing(12)
    if heading:
        box.addWidget(label(heading, 'section'))
    return w, box


class Background(QThread):
    result = Signal(object)
    failed = Signal(str)
    progress = Signal(object)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function

    def run(self):
        try:
            self.result.emit(self.function())
        except Exception as exc:
            # Network exceptions can contain tokens or signed URLs.
            if getattr(exc, 'user_safe', False):
                self.failed.emit(str(exc))
            else:
                self.failed.emit('操作失败：' + type(exc).__name__ + '。请检查配置、网络或文件权限。')


class SettingsPage(QWidget):
    saved = Signal(dict)

    def __init__(self, config):
        super().__init__()
        self.config = dict(config)
        self.testing = None
        self.update_check_task = None
        self.update_download_task = None
        self.update_info = None
        self.downloaded_update = None
        self.entries = []
        self.active = -1
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 18)
        heading = QHBoxLayout()
        heading.addWidget(label('设置', 'heading'), 1)
        outer.addLayout(heading)
        outer.addWidget(label('选择设置项目，在弹窗中查看和修改配置'))
        grid = QGridLayout()
        grid.setSpacing(18)
        outer.addLayout(grid)
        model, box = card('图片检测模型')
        form = QFormLayout()
        form.setSpacing(10)
        self.profiles = QComboBox()
        form.addRow('当前配置', self.profiles)
        self.model_fields = {}
        for key, text in [('name', '配置名称'), ('api_base', 'API 地址'), ('model', '模型名称'), ('api_key', 'API Key')]:
            edit = QLineEdit()
            edit.setAccessibleName(text)
            if key == 'api_key':
                edit.setEchoMode(QLineEdit.Password)
            self.model_fields[key] = edit
            form.addRow(text, edit)
        box.addLayout(form)
        actions = QHBoxLayout()
        actions.addWidget(btn('新增', self.new_profile))
        actions.addWidget(btn('删除', self.delete_profile))
        actions.addWidget(btn('导入配置', self.import_profiles))
        self.test_button = btn('测试图片识别', self.test_model)
        actions.addWidget(self.test_button)
        box.addLayout(actions)
        box.addWidget(label('密钥仅保存在本机；检测模型支持 OpenAI 兼容接口。'))

        updates, box = card('软件更新')
        box.addWidget(label(f'当前版本  v{APP_VERSION}', 'section'))
        box.addWidget(label(f'GitHub 更新源：{REPOSITORY}'))
        box.addWidget(label('检查更新不会影响当前任务；下载完成后由你确认是否安装。'))
        self.update_state = label('尚未检查更新。')
        box.addWidget(self.update_state)
        update_actions = QHBoxLayout()
        self.check_update_button = btn('检查更新', self.check_update, True)
        self.download_update_button = btn('下载更新', self.download_update)
        self.download_update_button.setEnabled(False)
        self.install_update_button = btn('安装已下载更新', self.install_downloaded_update)
        self.install_update_button.setEnabled(False)
        update_actions.addWidget(self.check_update_button)
        update_actions.addWidget(self.download_update_button)
        update_actions.addWidget(self.install_update_button)
        box.addLayout(update_actions)
        self.auto_update = QCheckBox('启动时自动检查更新')
        self.auto_update.setChecked(config.get('auto_check_update', True))
        box.addWidget(self.auto_update)
        box.addWidget(label('更新设计：保留模型配置、历史任务和浏览器数据。'))
        box.addWidget(label('任务运行时不会自动安装或重启；请先完成当前下载与检测。'))
        box.addStretch()

        rules, box = card('检测规则')
        self.phrases = QPlainTextEdit('\n'.join(config.get('phrases', PHRASES)))
        self.phrases.setMaximumHeight(108)
        box.addWidget(self.phrases)
        box.addWidget(label('红果 logo 检测：已启用', 'section'))
        box.addWidget(label('抽帧：实际首帧 + 1 秒 + 2 秒；短片自动调整。'))
        box.addWidget(label('修改规则或模型后，已有结果需重新检测。'))

        storage, box = card('任务与存储')
        self.fields = {}
        form = QFormLayout()
        for key, text in [('output_root', '素材保存目录'), ('logo_reference', '红果参考图'), ('parser_config_path', '解析配置'), ('downloader_config_path', '下载配置')]:
            edit = QLineEdit(config.get(key, ''))
            self.fields[key] = edit
            row = QHBoxLayout()
            row.addWidget(edit)
            row.addWidget(btn('浏览', lambda checked=False, e=edit, k=key: self.browse(e, k)))
            form.addRow(text, row)
        self.website = QLineEdit(config.get('platform_url', ''))
        self.website.setPlaceholderText('公司平台地址（待对齐）')
        form.addRow('平台地址', self.website)
        box.addLayout(form)
        box.addWidget(label('任务在独立进程中排队执行；当前并发上限为 1。'))
        self.restore = QCheckBox('启动时恢复上次批次（不自动执行）')
        self.restore.setChecked(config.get('restore_batch', True))
        box.addWidget(self.restore)
        box.addWidget(btn('打开日志目录', self.open_logs))
        self.message = label('设置仅保存在本机，修改后请保存。')
        outer.addWidget(self.message)
        outer.addStretch()
        self.dialogs = {}
        self.dialog_messages = {}
        sections = [
            ('model', '图片检测模型', '管理模型、API 地址与密钥，测试图片识别', model),
            ('updates', '软件更新', '检查版本与设置更新偏好 · 更新源待接入', updates),
            ('rules', '检测规则', '禁用文字、红果 logo 与片头抽帧规则', rules),
            ('storage', '任务与存储', '素材目录、下载参数、平台地址与历史恢复', storage),
        ]
        for index, (key, text, hint, content) in enumerate(sections):
            entry = btn(text + '\n\n' + hint + '\n\n打开设置  →',
                        lambda checked=False, k=key: self.open_section(k))
            entry.setMinimumHeight(140)
            entry.setStyleSheet('QPushButton { text-align:left; padding:22px; border-radius:10px; font-size:14px; }')
            grid.addWidget(entry, index // 2, index % 2)
            dialog = QDialog(self)
            dialog.setWindowTitle(text)
            dialog.resize(660, 560 if key == 'storage' else 510)
            dialog.setMinimumSize(500, 360)
            layout = QVBoxLayout(dialog)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(content)
            layout.addWidget(scroll, 1)
            feedback = label('修改后点击保存，取消不会保存本次修改。')
            layout.addWidget(feedback)
            actions = QHBoxLayout()
            actions.addStretch()
            actions.addWidget(btn('取消', dialog.reject))
            actions.addWidget(btn('保存', lambda checked=False, d=dialog: self.save_dialog(d), True))
            layout.addLayout(actions)
            self.dialogs[key] = dialog
            self.dialog_messages[key] = feedback
        try:
            data = json.loads(Path(config['model_config_path']).read_text(encoding='utf-8-sig'))
            self.entries = data.get('llm', {}).get('profiles', [])
        except (OSError, ValueError, KeyError):
            pass
        self.profiles.currentIndexChanged.connect(self.select_profile)
        self.rebuild_profiles(config.get('model_profile_id'))

    def set_message(self, text):
        self.message.setText(text)
        for key, dialog in self.dialogs.items():
            if dialog.isVisible():
                self.dialog_messages[key].setText(text)

    def open_section(self, key):
        self.capture()
        snapshot = (copy.deepcopy(self.entries), self.profiles.currentData(),
                    {k: e.text() for k, e in self.fields.items()}, self.phrases.toPlainText(),
                    self.website.text(), self.restore.isChecked(), self.auto_update.isChecked())
        self.dialog_messages[key].setText('修改后点击保存，取消不会保存本次修改。')
        if self.dialogs[key].exec() != QDialog.Accepted:
            entries, wanted, fields, phrases, website, restore, updates = snapshot
            self.entries = entries
            self.rebuild_profiles(wanted)
            for k, text in fields.items():
                self.fields[k].setText(text)
            self.phrases.setPlainText(phrases)
            self.website.setText(website)
            self.restore.setChecked(restore)
            self.auto_update.setChecked(updates)

    def save_dialog(self, dialog):
        if self.save():
            dialog.accept()

    def capture(self):
        if 0 <= self.active < len(self.entries):
            self.entries[self.active].update({k: e.text().strip() for k, e in self.model_fields.items()})

    def select_profile(self, index):
        self.capture()
        self.active = index
        p = self.entries[index] if 0 <= index < len(self.entries) else {}
        for k, e in self.model_fields.items():
            e.setText(p.get(k, ''))

    def rebuild_profiles(self, wanted=None):
        self.profiles.blockSignals(True)
        self.profiles.clear()
        for p in self.entries:
            self.profiles.addItem(p.get('name') or p.get('model') or '新配置', p.get('id'))
        index = max(0, self.profiles.findData(wanted)) if self.entries else -1
        self.profiles.setCurrentIndex(index)
        self.profiles.blockSignals(False)
        self.active = -1
        self.select_profile(index)

    def new_profile(self):
        self.capture()
        id_ = uuid.uuid4().hex
        self.entries.append({'id': id_, 'name': '新模型', 'enabled': True})
        self.rebuild_profiles(id_)

    def delete_profile(self):
        if self.active >= 0:
            self.entries.pop(self.active)
            self.rebuild_profiles()

    def import_profiles(self):
        path, _ = QFileDialog.getOpenFileName(self, '导入模型配置', '', 'JSON (*.json)')
        if path:
            try:
                entries = json.loads(Path(path).read_text(encoding='utf-8-sig'))['llm']['profiles']
                if not isinstance(entries, list) or not all(isinstance(p, dict) for p in entries):
                    raise ValueError()
                self.capture()
                self.entries.extend(dict(p, id=uuid.uuid4().hex) for p in entries)
                self.rebuild_profiles()
            except (OSError, ValueError, KeyError):
                self.set_message('配置文件无效。')

    def browse(self, edit, key):
        path = QFileDialog.getExistingDirectory(self, '素材保存目录', edit.text()) if key == 'output_root' else QFileDialog.getOpenFileName(self, '选择文件', edit.text())[0]
        if path:
            edit.setText(path)

    def open_logs(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(DATA_ROOT / 'runtime')))

    @staticmethod
    def _file_size(size):
        size = int(size or 0)
        if size < 1024 * 1024:
            return f'{size / 1024:.1f} KB'
        return f'{size / 1024 / 1024:.1f} MB'

    def check_update(self, silent=False):
        if self.update_check_task and self.update_check_task.isRunning():
            return
        self.check_update_button.setEnabled(False)
        if not silent:
            self.update_state.setText('正在连接 GitHub 查询最新版本…')

        def finished(info):
            self.update_info = info
            asset = info.get('asset')
            if not info.get('update_available'):
                self.update_state.setText(f"已是最新版本 v{info['current_version']}。")
                self.download_update_button.setEnabled(False)
                return
            if asset:
                self.update_state.setText(
                    f"发现 v{info['latest_version']}：{asset['name']}（{self._file_size(asset['size'])}）。"
                )
                self.download_update_button.setEnabled(True)
            else:
                self.update_state.setText(
                    f"发现 v{info['latest_version']}，但当前系统没有可下载的安装包；请到 Release 页面下载。"
                )
                self.download_update_button.setEnabled(False)
                QDesktopServices.openUrl(QUrl(info['release_url']))

        def failed(message):
            self.update_state.setText(message)
            if not silent:
                self.set_message(message)

        self.update_check_task = Background(check_for_update, self)
        self.update_check_task.result.connect(finished)
        self.update_check_task.failed.connect(failed)
        self.update_check_task.finished.connect(lambda: self.check_update_button.setEnabled(True))
        self.update_check_task.start()

    def download_update(self):
        asset = (self.update_info or {}).get('asset')
        if not asset or (self.update_download_task and self.update_download_task.isRunning()):
            return
        self.download_update_button.setEnabled(False)
        self.update_state.setText(f"正在下载 {asset['name']}…")

        def task():
            return download_update(
                asset,
                DATA_ROOT / 'runtime' / 'updates',
                progress=lambda data: self.update_download_task.progress.emit(data),
            )

        def progress(data):
            total = data.get('total') or 0
            downloaded = data.get('downloaded') or 0
            percent = f' {downloaded * 100 / total:.0f}%' if total else ''
            speed = self._file_size(data.get('bytes_per_second', 0)) + '/s'
            self.update_state.setText(f"正在下载更新{percent}：{self._file_size(downloaded)}，{speed}。")

        def finished(path):
            self.downloaded_update = Path(path)
            self.update_state.setText(f'更新包已下载：{self.downloaded_update.name}。可立即安装，或稍后在更新目录运行。')
            self.install_update_button.setEnabled(True)
            self.set_message(f'更新包已保存到：{self.downloaded_update}')

        def failed(message):
            self.update_state.setText(message)
            self.set_message(message)

        self.update_download_task = Background(task, self)
        self.update_download_task.progress.connect(progress)
        self.update_download_task.result.connect(finished)
        self.update_download_task.failed.connect(failed)
        self.update_download_task.finished.connect(lambda: self.download_update_button.setEnabled(bool((self.update_info or {}).get('asset'))))
        self.update_download_task.start()

    def install_downloaded_update(self):
        path = self.downloaded_update
        if not path or not path.is_file():
            self.install_update_button.setEnabled(False)
            self.update_state.setText('找不到已下载的更新包，请重新下载。')
            return
        if sys.platform.startswith('win') and path.suffix.lower() == '.exe':
            answer = QMessageBox.question(
                self,
                '安装更新',
                '安装程序将启动，并关闭当前软件以完成更新。是否继续？',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            if QProcess.startDetached(str(path), []):
                self.update_state.setText('安装程序已启动，软件将在片刻后退出。')
                QTimer.singleShot(600, lambda: self.window().close())
            else:
                self.update_state.setText('无法启动安装程序，请在更新目录手动运行。')
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        self.update_state.setText('已打开更新包，请按系统提示完成安装。')

    def active_background_tasks(self):
        return [
            task for task in (self.testing, self.update_check_task, self.update_download_task)
            if task is not None and task.isRunning()
        ]

    def test_model(self):
        self.capture()
        if self.active < 0:
            self.set_message('请先新增模型配置。')
            return
        p = dict(self.entries[self.active])
        if not all(p.get(k) for k in ('api_base', 'api_key', 'model')):
            self.set_message('请填写 API 地址、密钥和模型名称。')
            return
        def check():
            import requests
            response = requests.post(p['api_base'].rstrip('/') + '/chat/completions',
                headers={'Authorization': 'Bearer ' + p['api_key']},
                json={'model': p['model'], 'messages': [{'role': 'user', 'content': [
                    {'type': 'text', 'text': '请用一句中文描述图片中的图标。'},
                    image_part(RESOURCE_ROOT / 'assets/references/hongguo_logo.png')]}], 'max_tokens': 150}, timeout=(10, 45))
            response.raise_for_status()
            if not response.json().get('choices'):
                raise ValueError('missing choices')
            return '图片请求已收到模型响应；配置可连接。'
        self.test_button.setEnabled(False)
        self.set_message('正在后台测试图片识别…')
        self.testing = Background(check, self)
        self.testing.result.connect(self.set_message)
        self.testing.failed.connect(self.set_message)
        self.testing.finished.connect(lambda: self.test_button.setEnabled(True))
        self.testing.start()

    def save(self):
        from src.batch import save_json
        from PySide6.QtCore import QUrl
        self.capture()
        config = dict(self.config)
        config.update({k: e.text().strip() for k, e in self.fields.items()})
        config['phrases'] = list(dict.fromkeys(t.strip() for t in self.phrases.toPlainText().splitlines() if t.strip()))
        config['platform_url'] = self.website.text().strip()
        url = QUrl(config['platform_url'])
        if config['platform_url'] and (url.scheme() not in ('https', 'http') or not url.host() or url.userInfo()):
            self.set_message('请输入有效的 HTTP/HTTPS 平台地址。')
            return
        if not config['output_root'] or not config['phrases']:
            self.set_message('请填写素材目录和检测短语。')
            return
        path = DATA_ROOT / 'runtime/model_profiles.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            save_json(path, {'llm': {'profiles': self.entries}})
        except OSError:
            self.set_message('模型配置保存失败，请检查目录权限。')
            return
        config.update(model_config_path=str(path), model_profile_id=self.profiles.currentData() or '',
                      restore_batch=self.restore.isChecked(), auto_check_update=self.auto_update.isChecked())
        self.config = config
        self.saved.emit(config)
        self.set_message('设置已保存。')
        return True
