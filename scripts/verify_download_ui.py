"""Feed worker event-file progress to the actual desktop UI without network."""
import json
import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['MATERIAL_ASSISTANT_HOME'] = str(ROOT / 'output/download_progress_test')
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from src.desktop import MainWindow, configure_app
from src.task_input import links_to_rows
app = QApplication([])
configure_app(app)
w = MainWindow(False)
w.add_candidates(links_to_rows('https://www.douyin.com/video/123'))
w.event_path = w.runtime / 'progress-test.events.jsonl'
w.event_offset = 0
event = {'type':'download_progress', 'video_id':'123', 'received':32*1048576,
         'total':50*1048576, 'speed':2*1048576, 'percent':64}
w.event_path.write_text(json.dumps(event)+'\n', encoding='utf-8')
w.poll_events()
assert w.download_bar.value() == 640
assert '64.0%' in w.table.item(0, 2).text()
assert '32.0 MB / 50.0 MB' in w.transfer_detail.text()
w.show()
QTest.qWait(100)
w.grab().save(str(w.runtime.parent / 'download-progress.png'))
event.update(total=0, percent=None)
with w.event_path.open('a', encoding='utf-8') as handle:
    handle.write(json.dumps(event)+'\n')
w.poll_events()
assert w.download_bar.maximum() == 0
assert '总大小未知' in w.transfer_detail.text()
with w.event_path.open('a', encoding='utf-8') as handle:
    handle.write(json.dumps({'type':'progress','video_id':'123','stage':'完整性校验'})+'\n')
w.poll_events()
assert w.transfer_detail.text() == '完整性校验…'
w.close()
print('download-ui-ok: event-file delivery, bytes, speed, percent, unknown-size, validation transition')
