"""Build the lightweight Windows online installer with Inno Setup."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--version", required=True)
args = parser.parse_args()
if sys.platform != "win32":
    raise SystemExit("The Windows online installer must be built on Windows.")
compiler = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe"
if not compiler.is_file():
    raise SystemExit("Inno Setup 6 is required.")
subprocess.run([str(compiler), f"/DAppVersion={args.version}", "online_installer.iss"], cwd=ROOT, check=True)
