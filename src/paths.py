import os
import json
import shutil
import sys
from pathlib import Path

RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
FROZEN = bool(getattr(sys, "frozen", False))
APP_ROOT = Path(sys.executable).resolve().parent if FROZEN else RESOURCE_ROOT
_data_root_override = os.environ.get("MATERIAL_ASSISTANT_HOME", "").strip()
DATA_ROOT = Path(_data_root_override or APP_ROOT).resolve()
DEFAULT_USER_DATA_ROOT = (
    Path(os.environ.get("LOCALAPPDATA", DATA_ROOT / "runtime"))
    / "Dianzhong"
    / "MaterialAssistant"
)
USER_DATA_ROOT = Path(
    os.environ.get("MATERIAL_ASSISTANT_USER_HOME", DEFAULT_USER_DATA_ROOT)
).resolve()
# Development and explicit test roots continue to use the requested workspace.
# Installed builds keep user data outside their replaceable installation folder.
APP_DATA_ROOT = DATA_ROOT if _data_root_override or not FROZEN else USER_DATA_ROOT
APP_RUNTIME_ROOT = APP_DATA_ROOT / "runtime"


def _migrate_legacy_settings(legacy_runtime: Path, target_runtime: Path):
    """Move only user settings from old install folders, never caches or downloads."""
    if legacy_runtime.resolve() == target_runtime.resolve() or not legacy_runtime.is_dir():
        return
    target_runtime.mkdir(parents=True, exist_ok=True)
    names = ("desktop_config.json", "model_profiles.json", "upload-preferences.json", "downloader_config.json")
    for name in names:
        source, target = legacy_runtime / name, target_runtime / name
        if source.is_file() and not target.exists():
            shutil.copy2(source, target)
    config_path = target_runtime / "desktop_config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        if config.get("model_config_path") == str(legacy_runtime / "model_profiles.json"):
            config["model_config_path"] = str(target_runtime / "model_profiles.json")
            config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, ValueError, TypeError):
        pass


def prepare_environment():
    if FROZEN and not _data_root_override:
        _migrate_legacy_settings(DATA_ROOT / "runtime", APP_RUNTIME_ROOT)
    APP_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    binaries = RESOURCE_ROOT / "bin"
    if binaries.is_dir():
        os.environ["PATH"] = str(binaries) + os.pathsep + os.environ.get("PATH", "")
