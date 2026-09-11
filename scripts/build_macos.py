"""Build a native macOS application bundle without embedding credentials."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if sys.platform != "darwin":
    raise SystemExit("build_macos.py must run on macOS.")

command = [
    sys.executable,
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--windowed",
    "--name",
    "素材投放助手",
    "--osx-bundle-identifier",
    "com.dianzhong.materialassistant",
    "--distpath",
    str(ROOT / "release"),
    "--workpath",
    str(ROOT / "build"),
    "--specpath",
    str(ROOT / "build"),
    "--add-data",
    f"{ROOT / 'config.example.json'}:.",
    "--add-data",
    f"{ROOT / 'assets/references'}:assets/references",
    "--hidden-import",
    "src.vendor.browser_probe",
    "--hidden-import",
    "PySide6.QtWebEngineWidgets",
]
for name in ("ffmpeg", "ffprobe"):
    binary = shutil.which(name)
    if not binary:
        raise SystemExit(f"{name} is required on PATH")
    command.extend(["--add-binary", f"{binary}:bin"])

command.append(str(ROOT / "main.py"))
subprocess.run(command, cwd=ROOT, check=True)
print(ROOT / "release/素材投放助手.app")
