"""Build a standalone native Windows application, without embedding credentials."""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _find_real_binary(name: str) -> Path:
    """Return a standalone FFmpeg binary, never a Chocolatey shim."""
    found = shutil.which(name)
    if found:
        candidate = Path(found)
        try:
            if candidate.stat().st_size > 1_000_000:
                return candidate
        except OSError:
            pass

    chocolatey_root = Path(r"C:\ProgramData\chocolatey\lib")
    if chocolatey_root.is_dir():
        matches = sorted(chocolatey_root.glob(f"{name}/tools/**/{name}.exe"))
        if matches:
            return max(matches, key=lambda path: path.stat().st_size)
    raise SystemExit(f"{name} standalone binary is required; PATH points to a launcher shim")


command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir", "--windowed",
           "--name", "素材投放助手", "--distpath", str(ROOT / "release"), "--workpath", str(ROOT / "build"),
           "--specpath", str(ROOT / "build"), "--add-data", str(ROOT / "config.example.json") + ";.",
           "--add-data", str(ROOT / "assets/references") + ";assets/references",
           "--hidden-import", "src.vendor.browser_probe", "--hidden-import", "PySide6.QtWebEngineWidgets"]
for name in ["ffmpeg", "ffprobe"]:
    binary = _find_real_binary(name)
    command += ["--add-binary", str(binary) + ";bin"]
command.append(str(ROOT / "main.py"))
subprocess.run(command, cwd=ROOT, check=True)
print(ROOT / "release/素材投放助手/素材投放助手.exe")
