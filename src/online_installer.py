"""Small standalone bootstrapper distributed alongside the full desktop packages."""
from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from urllib.parse import urlparse
from urllib.request import Request, urlopen

REPOSITORY = "qilirampart/Material-management"
LATEST_RELEASE_PAGE_URL = f"https://github.com/{REPOSITORY}/releases/latest"
_TAG_PATH = re.compile(rf"^/{re.escape(REPOSITORY)}/releases/tag/v?(\d+(?:\.\d+){{1,2}})$")


def release_asset(system: str, version: str) -> tuple[str, str]:
    if system.lower() == "windows":
        name = f"DianzhongMaterialAssistant-Setup-{version}.exe"
    elif system.lower() == "darwin":
        name = f"DianzhongMaterialAssistant-macos-{version}.zip"
    else:
        raise ValueError(f"unsupported platform: {system}")
    return name, f"https://github.com/{REPOSITORY}/releases/download/v{version}/{name}"


def latest_release(request_open=urlopen) -> tuple[str, str]:
    request = Request(LATEST_RELEASE_PAGE_URL, headers={"User-Agent": "DianzhongMaterialAssistant-OnlineInstaller"})
    with request_open(request, timeout=20) as response:
        parsed = urlparse(response.geturl())
    match = _TAG_PATH.match(parsed.path)
    if parsed.scheme != "https" or parsed.hostname != "github.com" or not match:
        raise RuntimeError("无法识别 GitHub 的最新发布版本。")
    return match.group(1), f"https://github.com{parsed.path}"


def update_directory() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache")) / "Dianzhong" / "MaterialAssistant" / "online-installer"


def download_latest(progress=None, request_open=urlopen, system=None, destination=None) -> tuple[Path, str]:
    version, _ = latest_release(request_open)
    name, url = release_asset(system or platform.system(), version)
    destination = Path(destination or update_directory())
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / name
    partial = target.with_suffix(target.suffix + ".part")
    request = Request(url, headers={"User-Agent": "DianzhongMaterialAssistant-OnlineInstaller"})
    try:
        with request_open(request, timeout=90) as response, partial.open("wb") as stream:
            total, written, started = int(response.headers.get("Content-Length") or 0), 0, time.monotonic()
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
                written += len(chunk)
                if progress:
                    progress(written, total, written / max(time.monotonic() - started, 0.001))
        if total and written != total:
            raise RuntimeError("下载不完整，请重新运行在线安装器。")
        os.replace(partial, target)
        return target, version
    finally:
        if partial.exists():
            partial.unlink(missing_ok=True)


class InstallerWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("点众素材投放助手 - 在线安装器")
        self.root.resizable(False, False)
        self.root.geometry("520x225")
        self.status = tk.StringVar(value="正在准备下载最新版本…")
        self.detail = tk.StringVar(value="下载完成后会自动启动安装程序。")
        frame = ttk.Frame(self.root, padding=24); frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="点众素材投放助手", font=("Microsoft YaHei", 17, "bold")).pack(anchor="w")
        ttk.Label(frame, text="在线安装器", font=("Microsoft YaHei", 10)).pack(anchor="w", pady=(3, 18))
        ttk.Label(frame, textvariable=self.status).pack(anchor="w")
        self.progress = ttk.Progressbar(frame, mode="determinate", maximum=100); self.progress.pack(fill="x", pady=(12, 8))
        ttk.Label(frame, textvariable=self.detail).pack(anchor="w")
        self.retry = ttk.Button(frame, text="重试", command=self.start); self.retry.pack(anchor="e", pady=(12, 0)); self.retry.state(["disabled"])

    def update_progress(self, written, total, speed):
        def apply():
            if total:
                self.progress.configure(value=written * 100 / total)
                self.detail.set(f"{written / 1048576:.1f} / {total / 1048576:.1f} MB · {speed / 1048576:.1f} MB/s")
            else:
                self.progress.configure(mode="indeterminate"); self.progress.start(12)
        self.root.after(0, apply)

    def start(self):
        self.retry.state(["disabled"]); self.progress.stop(); self.progress.configure(mode="determinate", value=0)
        self.status.set("正在获取最新版本…")
        threading.Thread(target=self._download, daemon=True).start()

    def _download(self):
        try:
            target, version = download_latest(self.update_progress)
        except Exception as exc:
            self.root.after(0, lambda: self._failed(str(exc))); return
        self.root.after(0, lambda: self._finished(target, version))

    def _failed(self, message):
        self.progress.stop(); self.status.set("下载失败，请检查网络后重试。"); self.detail.set(message); self.retry.state(["!disabled"])

    def _finished(self, target, version):
        self.progress.stop(); self.progress.configure(value=100); self.status.set(f"v{version} 已下载，正在启动安装程序…"); self.detail.set(target.name)
        try:
            subprocess.Popen([str(target)] if sys.platform.startswith("win") else ["open", str(target)], close_fds=True)
        except OSError as exc:
            self._failed(f"无法启动下载的安装包：{exc}"); return
        self.root.after(900, self.root.destroy)

    def run(self):
        self.start(); self.root.mainloop()


if __name__ == "__main__":
    InstallerWindow().run()
