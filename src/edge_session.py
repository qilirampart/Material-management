from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from src.paths import DATA_ROOT


EDGE_LOCATIONS = (
    Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
    / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
    / "Microsoft/Edge/Application/msedge.exe",
)


def persistent_edge_profile(config: dict) -> Path:
    configured = str(config.get("edge_profile_path", "")).strip()
    return Path(configured).expanduser().resolve() if configured else DATA_ROOT / "runtime" / "edge-cdp-profile"


def find_edge() -> Path:
    for candidate in EDGE_LOCATIONS:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("未找到 Microsoft Edge，请确认 Edge 已安装。")


def build_edge_command(url: str, profile: Path, port: int = 9222) -> list[str]:
    parsed = urlsplit(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("平台地址无效，请填写 http 或 https 地址。")
    return [
        str(find_edge()),
        f"--remote-debugging-port={int(port)}",
        f"--user-data-dir={profile.resolve()}",
        "--new-window",
        url.strip(),
    ]


def open_persistent_edge(url: str, config: dict) -> Path:
    profile = persistent_edge_profile(config)
    profile.mkdir(parents=True, exist_ok=True)
    command = build_edge_command(url, profile, int(config.get("edge_debug_port", 9222)))
    creation_flags = 0
    if os.name == "nt":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creation_flags,
    )
    return profile
