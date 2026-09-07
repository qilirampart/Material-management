"""Build a standalone native Windows application, without embedding credentials."""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir", "--windowed",
           "--name", "素材投放助手", "--distpath", str(ROOT / "release"), "--workpath", str(ROOT / "build"),
           "--specpath", str(ROOT / "build"), "--add-data", str(ROOT / "config.example.json") + ";.",
           "--add-data", str(ROOT / "assets/references") + ";assets/references",
           "--hidden-import", "src.vendor.browser_probe", "--hidden-import", "PySide6.QtWebEngineWidgets"]
for name in ["ffmpeg", "ffprobe"]:
    binary = shutil.which(name)
    if not binary:
        raise SystemExit(name + " is required on PATH")
    command += ["--add-binary", binary + ";bin"]
command.append(str(ROOT / "main.py"))
subprocess.run(command, cwd=ROOT, check=True)
print(ROOT / "release/素材投放助手/素材投放助手.exe")
