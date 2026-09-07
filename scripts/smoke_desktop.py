"""Exercise real Qt widgets and save native-window screenshots; no network calls."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MATERIAL_ASSISTANT_HOME", str(ROOT / "output" / "desktop_smoke"))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from src.desktop import MainWindow, configure_app
from src.batch import save_json


app = QApplication([])
configure_app(app)
window = MainWindow(restore=False)
folder = ROOT / "output" / "desktop_smoke" / "batch"
folder.mkdir(parents=True, exist_ok=True)
state = json.loads((ROOT / "output" / "pilot" / "results.json").read_text(encoding="utf-8"))
state["input_path"] = str(ROOT / "懂小剧素材_婚房门后的秘密.xlsx")
save_json(folder / "results.json", state)
save_json(folder / "reviews.json", {})
window.open_batch(folder)
window.resize(1366, 840)
window.show()
QTest.qWait(250)
assert window.table.rowCount() == 200
window.search.setText("7681538825608236331")
assert sum(not window.table.isRowHidden(i) for i in range(200)) == 1
window.search.clear()
window.grab().save(str(folder.parent / "tasks.png"))
window.table.selectRow(0)
window.open_selected()
QTest.qWait(450)
window.review.player.play()
QTest.qWait(250)
window.review.player.pause()
assert window.review.player.position() > 0, "Video playback did not advance"
assert window.review.video_id == "7681538825608236331"
assert window.review.frames_layout.count() == 3
window.review.note.setPlainText("桌面自动测试：证据可查看")
window.review.save_note()
assert json.loads((folder / "reviews.json").read_text(encoding="utf-8"))[window.review.video_id]["note"]
window.grab().save(str(folder.parent / "review.png"))
window.review.block()
assert window.notes[window.review.video_id]["blocked"]
window.navigation.setCurrentRow(0)
window.export()
assert (folder / "复核结果.xlsx").is_file()
window.resize(1000, 720)
window.navigation.setCurrentRow(3)
QTest.qWait(150)
window.grab().save(str(folder.parent / "settings-small.png"))
window.resize(1366, 840)
window.navigation.setCurrentRow(2)
window.grab().save(str(folder.parent / "platform.png"))
window.navigation.setCurrentRow(0)
# The three downloaded files are deliberately handled without model/network activity.
window.mode.setCurrentIndex(1)
window.start_batch(["7681538825608236331", "7681339570746674495", "7681349410751647003"])
window.pause()
for _ in range(500):
    QTest.qWait(100)
    if not window.is_running():
        break
assert not window.is_running(), "Worker did not pause within 50 seconds"
events = [json.loads(line) for line in window.event_path.read_text(encoding="utf-8").splitlines()]
assert any(e["type"] == "paused" for e in events), events
assert window.import_button.isEnabled()
window.close()
print("desktop-smoke-ok: 200 rows, search, video, 3 frames, notes, block, export, navigation, worker pause")
