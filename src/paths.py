import os
import sys
from pathlib import Path

RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
APP_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else RESOURCE_ROOT
DATA_ROOT = Path(os.environ.get("MATERIAL_ASSISTANT_HOME", APP_ROOT)).resolve()
DEFAULT_USER_DATA_ROOT = (
    Path(os.environ.get("LOCALAPPDATA", DATA_ROOT / "runtime"))
    / "Dianzhong"
    / "MaterialAssistant"
)
USER_DATA_ROOT = Path(
    os.environ.get("MATERIAL_ASSISTANT_USER_HOME", DEFAULT_USER_DATA_ROOT)
).resolve()


def prepare_environment():
    binaries = RESOURCE_ROOT / "bin"
    if binaries.is_dir():
        os.environ["PATH"] = str(binaries) + os.pathsep + os.environ.get("PATH", "")
