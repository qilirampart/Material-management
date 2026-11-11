from __future__ import annotations

from pathlib import Path

from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import QApplication

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


def shared_platform_profile(config, *, owner=None):
    """One Qt profile per storage directory, shared only for platform login."""
    owner = owner if owner is not None else QApplication.instance()
    if owner is None:
        raise RuntimeError('请先启动桌面应用')
    if not hasattr(owner, '_material_platform_profiles'):
        owner._material_platform_profiles = {}
    root = platform_browser_root(config)
    key = str(root)
    profiles = owner._material_platform_profiles
    if key not in profiles:
        profile = QWebEngineProfile('company-platform', owner)
        configure_persistent_profile(profile, root)
        profiles[key] = profile
    return profiles[key]
