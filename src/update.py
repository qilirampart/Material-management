"""GitHub Release update discovery and download helpers."""
from __future__ import annotations

import os
import platform
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests


APP_VERSION = "0.4.6"
REPOSITORY = "qilirampart/Material-management"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
LATEST_RELEASE_PAGE_URL = f"https://github.com/{REPOSITORY}/releases/latest"
_VERSION_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?$")


class UpdateError(RuntimeError):
    """An update error that is safe to show to the user."""

    user_safe = True


def version_key(value: str) -> tuple[int, int, int]:
    match = _VERSION_RE.match(str(value).strip())
    if not match:
        raise UpdateError(f"发布版本号格式无效：{value}")
    return tuple(int(part or 0) for part in match.groups())


def _platform_asset(assets: list[dict], system: str | None = None) -> dict | None:
    system = (system or platform.system()).lower()
    suffix = ".exe" if system == "windows" else ".zip" if system == "darwin" else ""
    if not suffix:
        return None
    candidates = [asset for asset in assets if str(asset.get("name", "")).lower().endswith(suffix)]
    preferred = [asset for asset in candidates if "dianzhongmaterialassistant" in str(asset.get("name", "")).lower()]
    return (preferred or candidates or [None])[0]


def _safe_download_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in {"github.com", "objects.githubusercontent.com"}:
        raise UpdateError("更新包地址无效，请稍后重试。")
    return value


def _redirect_release_fallback(*, current_version: str, system: str | None, request_get) -> dict:
    """Use GitHub's public latest-release redirect when API quota is exhausted."""
    try:
        response = request_get(
            LATEST_RELEASE_PAGE_URL,
            headers={"User-Agent": "DianzhongMaterialAssistant"},
            timeout=(5, 20),
            allow_redirects=True,
        )
        response.raise_for_status()
        parsed = urlparse(str(response.url))
    except requests.RequestException as exc:
        raise UpdateError("GitHub 更新服务暂时不可用，请稍后重试。") from exc
    expected_prefix = f"/{REPOSITORY}/releases/tag/"
    if parsed.scheme != "https" or parsed.hostname != "github.com" or not parsed.path.startswith(expected_prefix):
        raise UpdateError("无法识别 GitHub 最新发布版本，请稍后重试。")
    latest_version = parsed.path[len(expected_prefix):].lstrip("v")
    latest_key = version_key(latest_version)
    system = (system or platform.system()).lower()
    if system == "windows":
        name = f"DianzhongMaterialAssistant-Setup-{latest_version}.exe"
    elif system == "darwin":
        name = f"DianzhongMaterialAssistant-macos-{latest_version}.zip"
    else:
        name = ""
    asset = None
    if name:
        asset = {
            "name": name,
            "url": _safe_download_url(f"https://github.com/{REPOSITORY}/releases/download/v{latest_version}/{name}"),
            "size": 0,
        }
    return {
        "current_version": current_version,
        "latest_version": latest_version,
        "update_available": latest_key > version_key(current_version),
        "release_url": _safe_download_url(f"https://github.com{parsed.path}"),
        "asset": asset,
        "notes": "通过 GitHub Release 页面查询（API 配额已满）。",
    }


def check_for_update(*, current_version: str = APP_VERSION, system: str | None = None, request_get=requests.get) -> dict:
    """Return update metadata from the repository's latest public release."""
    try:
        response = request_get(
            LATEST_RELEASE_URL,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "DianzhongMaterialAssistant"},
            timeout=(5, 20),
        )
        response.raise_for_status()
        payload = response.json()
    except requests.HTTPError as exc:
        if getattr(exc.response, "status_code", None) == 403:
            return _redirect_release_fallback(
                current_version=current_version,
                system=system,
                request_get=request_get,
            )
        raise UpdateError("GitHub 更新服务暂时不可用，请稍后重试。") from exc
    except requests.RequestException as exc:
        raise UpdateError("无法连接 GitHub 更新服务，请检查网络后重试。") from exc
    except (TypeError, ValueError) as exc:
        raise UpdateError("GitHub 返回的更新信息无效，请稍后重试。") from exc

    if not isinstance(payload, dict) or payload.get("draft"):
        raise UpdateError("GitHub 尚未提供可用更新版本。")
    latest_version = str(payload.get("tag_name", "")).lstrip("v")
    latest_key = version_key(latest_version)
    current_key = version_key(current_version)
    assets = payload.get("assets", [])
    if not isinstance(assets, list):
        assets = []
    asset = _platform_asset(assets, system)
    if asset and asset.get("browser_download_url"):
        asset = {
            "name": str(asset.get("name", "更新包")),
            "url": _safe_download_url(str(asset["browser_download_url"])),
            "size": int(asset.get("size") or 0),
        }
    else:
        asset = None
    return {
        "current_version": current_version,
        "latest_version": latest_version,
        "update_available": latest_key > current_key,
        "release_url": _safe_download_url(str(payload.get("html_url", f"https://github.com/{REPOSITORY}/releases/latest"))),
        "asset": asset,
        "notes": str(payload.get("body") or "").strip(),
    }


def download_update(asset: dict, destination_dir: Path, progress=None, request_get=requests.get) -> Path:
    """Download a selected release asset atomically and report byte progress."""
    url = _safe_download_url(str(asset.get("url", "")))
    name = Path(str(asset.get("name", "更新包"))).name
    if not name or name in {".", ".."}:
        raise UpdateError("更新包文件名无效。")
    destination_dir.mkdir(parents=True, exist_ok=True)
    target = destination_dir / name
    partial = target.with_suffix(target.suffix + ".part")
    try:
        response = request_get(url, stream=True, timeout=(10, 90), headers={"User-Agent": "DianzhongMaterialAssistant"})
        response.raise_for_status()
        total = int(response.headers.get("content-length") or asset.get("size") or 0)
        written = 0
        started = time.monotonic()
        with partial.open("wb") as stream:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                stream.write(chunk)
                written += len(chunk)
                if progress:
                    elapsed = max(time.monotonic() - started, 0.001)
                    progress({"downloaded": written, "total": total, "bytes_per_second": written / elapsed})
        if total and written != total:
            raise UpdateError("更新包下载不完整，请重试。")
        os.replace(partial, target)
        return target
    except UpdateError:
        raise
    except (OSError, requests.RequestException) as exc:
        raise UpdateError("更新包下载失败，请检查网络和本地磁盘空间后重试。") from exc
    finally:
        if partial.exists():
            try:
                partial.unlink()
            except OSError:
                pass
