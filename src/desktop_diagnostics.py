"""Offline diagnostic for the packaged native application."""
import json
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from src.desktop import MainWindow, configure_app
from src.media import run


def smoke(output):
    folder = Path(output)
    folder.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    configure_app(app)
    window = MainWindow(restore=False)
    window.show()
    result = {}

    def finish():
        try:
            for i, name in enumerate(["tasks", "review", "platform", "settings"]):
                window.navigation.setCurrentRow(i)
                app.processEvents()
                window.grab().save(str(folder / (name + ".png")))
            # Load a local page in the real embedded browser. No external site or login.
            from PySide6.QtWebEngineWidgets import QWebEngineView
            browser = QWebEngineView(window)
            browser.loadFinished.connect(browser_loaded)
            browser.setHtml("<html><body><h1>Desktop browser ready</h1></body></html>")
            result["browser"] = browser
        except Exception as exc:
            save(False, str(exc))

    def browser_loaded(ok):
        try:
            ffmpeg = run(["ffmpeg", "-version"]).splitlines()[0]
            save(ok, ffmpeg)
        except Exception as exc:
            save(False, str(exc))

    def save(ok, message):
        (folder / "result.json").write_text(json.dumps({"ok": ok, "pages": window.pages.count(), "message": message}, ensure_ascii=False), encoding="utf-8")
        window.close()
        app.exit(0 if ok else 1)

    QTimer.singleShot(250, finish)
    QTimer.singleShot(25000, lambda: save(False, "diagnostic timed out"))
    return app.exec()
