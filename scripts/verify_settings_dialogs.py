"""Native UI verification of modal settings, cancel and save."""
import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['MATERIAL_ASSISTANT_HOME'] = str(ROOT / 'output/settings_dialogs')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from src.desktop import MainWindow, configure_app
app = QApplication([])
configure_app(app)
w = MainWindow(False)
w.navigation.setCurrentRow(3)
w.show()
QTest.qWait(100)
folder = ROOT / 'output/settings_dialogs'
folder.mkdir(parents=True, exist_ok=True)
w.grab().save(str(folder / 'settings-home.png'))
s = w.settings
assert not s.model_fields['api_key'].isVisible()
previous = s.phrases.toPlainText()
def cancel_rules():
    s.phrases.setPlainText('取消测试')
    s.dialogs['rules'].reject()
QTimer.singleShot(80, cancel_rules)
s.open_section('rules')
assert s.phrases.toPlainText() == previous
def model_preview():
    assert s.model_fields['api_key'].isVisible()
    s.set_message('弹窗内反馈测试')
    assert s.dialog_messages['model'].text() == '弹窗内反馈测试'
    s.dialogs['model'].grab().save(str(folder / 'model-dialog.png'))
    s.dialogs['model'].reject()
QTimer.singleShot(120, model_preview)
s.open_section('model')
def save_rules():
    s.phrases.setPlainText(previous + '\n测试规则')
    s.save_dialog(s.dialogs['rules'])
QTimer.singleShot(80, save_rules)
s.open_section('rules')
assert '测试规则' in w.config['phrases']
assert all(not d.isVisible() for d in s.dialogs.values())
w.close()
print('settings-dialogs-ok: hidden forms, modal open, inline feedback, cancel rollback, save persistence')
