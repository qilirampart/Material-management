"""Build the lightweight online installer on its target operating system."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "DianzhongMaterialAssistant-OnlineInstaller"

parser = argparse.ArgumentParser()
parser.add_argument("--distpath", default=str(ROOT / "release"))
args = parser.parse_args()
distpath = Path(args.distpath).resolve()
workpath = ROOT / "build" / "online-installer"
specpath = ROOT / "build" / "online-installer-spec"
shutil.rmtree(workpath, ignore_errors=True)
shutil.rmtree(specpath, ignore_errors=True)
subprocess.run([
    sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
    "--name", NAME, "--distpath", str(distpath), "--workpath", str(workpath),
    "--specpath", str(specpath), str(ROOT / "src" / "online_installer.py"),
], cwd=ROOT, check=True)
