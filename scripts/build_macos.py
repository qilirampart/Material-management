"""Build a native macOS application bundle without embedding credentials."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if sys.platform != "darwin":
    raise SystemExit("build_macos.py must run on macOS.")


def prepare_icon() -> Path:
    source = ROOT / "assets" / "icons" / "app-icon.png"
    iconset = ROOT / "build" / "app-icon.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    for size, name in ((16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
                       (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
                       (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
                       (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
                       (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png")):
        subprocess.run(["sips", "-z", str(size), str(size), str(source), "--out", str(iconset / name)], check=True)
    output = ROOT / "build" / "app-icon.icns"
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(output)], check=True)
    return output


ICON = prepare_icon()
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
    "--icon",
    str(ICON),
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
