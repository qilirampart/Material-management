"""Isolated acceptance: Qt + real download worker + loopback + real MP4s."""
import argparse
from contextlib import contextmanager, nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@contextmanager
def media_server(clip):
    streaming, release = threading.Event(), threading.Event()
    data = clip.read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/parse?"):
                body = json.dumps({"video_url": f"http://127.0.0.1:{self.server.server_port}/clip.mp4"}).encode()
                kind = "application/json"
            elif self.path == "/clip.mp4":
                body, kind = data, "video/mp4"
                streaming.set()
                release.wait(20)
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/parse", streaming, release
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join()


def verify(here, artifacts, native, live_url=None):
    from openpyxl import Workbook
    from PySide6.QtCore import QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon
    from src.batch import HEADERS
    from src.desktop import MainWindow, configure_app
    from src.media import probe, run, validate_video
    from src.recreation import RecreationBatch

    def wait_until(predicate, label, ms=16000):
        deadline = time.monotonic() + ms / 1000
        while not predicate():
            if time.monotonic() > deadline:
                raise AssertionError(label)
            QTest.qWait(35)

    runtime = here/"runtime"
    runtime.mkdir()
    clip = here/"fixture.mp4"
    run(["ffmpeg","-v","error","-y","-f","lavfi","-i",
         "testsrc2=size=240x320:rate=25:duration=2","-c:v","libx264",str(clip)])
    app = QApplication([])
    configure_app(app)
    server = nullcontext((None, None, None)) if live_url else media_server(clip)
    with server as (parser, streaming, release):
        api = runtime/"api_config.json"
        downloader = runtime/"downloader_config.json"
        providers = [{"name":"loopback fixture", "base_url":parser}] if parser else []
        write_json(api, {"douyin_parser": {"providers": providers}})
        write_json(downloader, {"browser_first_enabled":bool(live_url), "fast_resolve_enabled":True,
                                "browser_probe_timeout_seconds":35, "slow_retry_enabled":False})
        write_json(runtime/"desktop_config.json", {
            "output_root":str(here/"output"), "parser_config_path":str(api),
            "downloader_config_path":str(downloader), "restore_batch":False,
            "md5_lanes":2, "md5_overlap":True, "desktop_notices":True,
            "minimum_video_short_edge":0,
        })
        window = MainWindow(restore=False)
        window.setWindowTitle("点众素材投放助手｜并发与提醒验收")
        window.resize(1180, 780)
        window.show()
        page = window.recreation
        md5 = page.md5
        batch = page.workspace.create("4100-验收合成视频")[0]
        copies = [here/"first.mp4", here/"second.mp4"]
        for path in copies:
            path.write_bytes(clip.read_bytes())
        batch.add_local_sources(list(map(str,copies)), batch.state["dramas"][0])
        page.workspace.add_inputs("md5", batch.folder, [item["video_id"] for item in batch.state["sources"]])
        md5.uploader.setText("QA")
        md5.refresh()
        page.set_checked(md5.table,"all")
        window.folder = here/"legacy"
        window.folder.mkdir()
        window.input_path = window.folder/"input.xlsx"
        video_id = live_url.rsplit("/",1)[-1] if live_url else "4100000000000000001"
        url = live_url or f"https://www.douyin.com/video/{video_id}"
        book = Workbook()
        book.active.append(list(HEADERS))
        book.active.append(["验收视频", video_id, 0, 0, "", url])
        book.save(window.input_path)
        window.mode.setCurrentIndex(window.mode.findData("download"))
        window.start_batch([video_id])
        try:
            if streaming:
                wait_until(streaming.is_set, "download worker did not reach the loopback media endpoint")
            else:
                wait_until(lambda: window.process is not None and
                           window.process.state() == window.process.ProcessState.Running,
                           "public-download worker did not start")
            assert window.recreation.legacy_download_active.is_set()
            window.navigation.setCurrentRow(4)
            page.tabs.setCurrentIndex(2)
            choices = []

            def answer():
                dialog = app.activeModalWidget()
                if not isinstance(dialog, QMessageBox):
                    return
                choices.append(dialog.defaultButton().text())
                dialog.grab().save(str(artifacts/"download-conflict.png"))
                dialog.defaultButton().click()

            QTimer.singleShot(100, answer)
            md5.start()
            assert choices == ["本轮用 1 路"], (choices, md5.status.text())
            wait_until(lambda: not md5.busy, "MD5 jobs did not finish")
            if streaming:
                assert window.is_running(), "legacy subprocess ended before MD5 completion"
            outputs = RecreationBatch.load(batch.folder).state["outputs"]
            assert len(outputs) == 2, md5.status.text()
            for output in outputs:
                assert output["output_md5"] != output["source_md5"]
                validate_video(output["path"])
            if release:
                release.set()
            wait_until(lambda: not window.is_running(), "legacy subprocess did not finish", 180000 if live_url else 16000)
            wait_until(lambda: not page.legacy_download_active.is_set(), "download-active flag not released")
            record = json.loads((window.folder/"results.json").read_text(encoding="utf-8"))["records"][video_id]
            assert record["download"] == "已下载", record
            assert window.worker_outcome == "completed", window.last_worker_error
            assert (window.folder/"检测结果.xlsx").is_file()
            metadata = probe(record["video_path"])
            assert len(window.notices.feed.items) == 2
            assert window.notices.feed.items[0].title == "素材任务本轮结束"
            transport = "public Douyin video" if live_url else "loopback HTTP"
            print(f"PASS: {transport} worker + MD5; sample duration={metadata['duration']:.2f}s; "
                  "both MD5 files and their records verified",flush=True)

            if native:
                tray_support = QSystemTrayIcon.isSystemTrayAvailable() and QSystemTrayIcon.supportsMessages()
                if not tray_support:
                    print("SYSTEM TRAY UNAVAILABLE",flush=True)
                else:
                    window.showMinimized()
                    wait_until(lambda: window.notices.shown is not None, "system tray was not invoked")
                    print("SYSTEM TRAY INVOKED: waiting 12 seconds for Windows verification",flush=True)
                    QTest.qWait(12000)
            window.grab().save(str(artifacts/"acceptance-main.png"))
        finally:
            if release:
                release.set()
            if window.is_running():
                window.pause()
                wait_until(lambda: not window.is_running(), "worker did not stop")
            window.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--live-url", help="one public douyin.com/video URL; no logged-in profile")
    args = parser.parse_args()
    if args.live_url and not re.fullmatch(r"https://www\.douyin\.com/video/\d{10,25}", args.live_url):
        parser.error("--live-url must be a public https://www.douyin.com/video/<id> URL")
    artifacts = ROOT/"tmp"/"speed-acceptance"
    artifacts.mkdir(parents=True, exist_ok=True)
    if not args.native:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    with tempfile.TemporaryDirectory(prefix="fixture-",dir=artifacts) as directory:
        os.environ["MATERIAL_ASSISTANT_HOME"] = directory
        verify(Path(directory), artifacts, args.native, args.live_url)
