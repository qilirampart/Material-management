"""Exercise candidate selection, settings persistence and UI heartbeat without network."""
import os
import sys
import time
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['MATERIAL_ASSISTANT_HOME'] = str(ROOT / 'output/ui_v2_test')
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import QTimer, Qt
from src.desktop import MainWindow, configure_app
from src.task_input import links_to_rows
from src.ui_design import Background, SettingsPage
app = QApplication([])
configure_app(app)
w = MainWindow(False)
w.new_batch()
w.add_candidates(links_to_rows('https://www.douyin.com/video/123 https://v.douyin.com/ABC/'))
assert w.selected_ids() == []
w.table.item(0, 0).setCheckState(Qt.Checked)
assert w.selected_ids() == ['123']
w.search.setText('link_')
assert w.selected_ids() == []  # Hidden selections must not execute.
w.search.clear()
assert w.selected_ids() == ['123']
w.check_visible(False)
assert w.selected_ids() == []
assert [w.mode.itemData(i) for i in range(3)] == ['both', 'download', 'detect']
assert len(w.rows) == 2
w.add_candidates(links_to_rows('https://www.douyin.com/video/123'))
assert len(w.rows) == 2
# Isolated fake credentials exercise round-trip, never the user's real key.
settings = SettingsPage({'output_root': str(ROOT / 'output/ui_v2_test'), 'model_config_path': ''})
settings.new_profile()
for k, v in {'name':'test','model':'vision-test','api_base':'https://example.invalid/v1','api_key':'fake-test-only'}.items():
    settings.model_fields[k].setText(v)
saved = []
settings.saved.connect(saved.append)
settings.save()
assert saved and 'api_key' not in saved[0]
again = SettingsPage(saved[0])
assert again.model_fields['api_key'].text() == 'fake-test-only'
settings.deleteLater()
again.deleteLater()
ticks = []
timer = QTimer()
timer.setInterval(20)
timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
timer.start()
worker = Background(lambda: time.sleep(0.6))
worker.start()
w.show()
QTest.qWait(700)
worker.wait()
timer.stop()
assert len(ticks) >= 10, len(ticks)
gap = max(b-a for a,b in zip(ticks, ticks[1:]))
assert gap < .25, gap
w.close()
print(json.dumps({'selection_modes_settings':'passed','background_ui_ticks':len(ticks),'max_gap_ms':round(gap*1000)}))
