from __future__ import annotations

from pathlib import Path

from PySide6.QtWebEngineCore import QWebEngineProfile

from src.paths import USER_DATA_ROOT


def platform_browser_root(config: dict) -> Path:
    configured = str(config.get("platform_browser_data_path", "")).strip()
    return Path(configured).expanduser().resolve() if configured else USER_DATA_ROOT / "browser"


def configure_persistent_profile(profile: QWebEngineProfile, root: Path) -> None:
    root = Path(root).resolve()
    storage = root / "storage"
    cache = root / "cache"
    storage.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    profile.setPersistentStoragePath(str(storage))
    profile.setCachePath(str(cache))
    profile.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
    )
    profile.setPersistentPermissionsPolicy(
        QWebEngineProfile.PersistentPermissionsPolicy.StoreOnDisk
    )
