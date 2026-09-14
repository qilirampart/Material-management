"""Build a native small macOS online installer app and package it as a zip."""
from __future__ import annotations

import argparse
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if sys.platform != "darwin":
    raise SystemExit("macOS online installer must be built on macOS.")

parser = argparse.ArgumentParser()
parser.add_argument("--version", required=True)
args = parser.parse_args()
version = args.version
name = "DianzhongMaterialAssistant-Downloader"
app = ROOT / "release" / f"{name}.app"
contents = app / "Contents"
macos = contents / "MacOS"
resources = contents / "Resources"
shutil.rmtree(app, ignore_errors=True)
macos.mkdir(parents=True)
resources.mkdir(parents=True)

iconset = ROOT / "build" / "online-installer-icon.iconset"
iconset.mkdir(parents=True, exist_ok=True)
source_icon = ROOT / "assets" / "icons" / "app-icon.png"
for size, filename in ((16, "icon_16x16.png"), (32, "icon_16x16@2x.png"), (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"), (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"), (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"), (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png")):
    subprocess.run(["sips", "-z", str(size), str(size), str(source_icon), "--out", str(iconset / filename)], check=True)
icon = resources / "AppIcon.icns"
subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icon)], check=True)

template = (ROOT / "scripts" / "macos_online_installer.swift").read_text(encoding="utf-8")
source = ROOT / "build" / "macos-online-installer.swift"
source.write_text(template.replace("__VERSION__", version), encoding="utf-8")
binary = macos / name
subprocess.run(["swiftc", str(source), "-framework", "Cocoa", "-o", str(binary)], check=True)
(contents / "Info.plist").write_bytes(plistlib.dumps({
    "CFBundleName": "点众素材投放助手在线安装器",
    "CFBundleDisplayName": "点众素材投放助手在线安装器",
    "CFBundleIdentifier": "com.dianzhong.materialassistant.downloader",
    "CFBundleExecutable": name,
    "CFBundleIconFile": "AppIcon",
    "CFBundlePackageType": "APPL",
    "CFBundleShortVersionString": version,
    "CFBundleVersion": version,
    "LSMinimumSystemVersion": "11.0",
    "CFBundleName": "Dianzhong Material Assistant Downloader",
    "CFBundleDisplayName": "Dianzhong Material Assistant Downloader",
}))
archive = ROOT / "release" / f"{name}-macos-{version}.zip"
if archive.exists(): archive.unlink()
subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(archive)], check=True)
