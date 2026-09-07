from __future__ import annotations

import os
import subprocess
import ctypes
from ctypes import wintypes
from pathlib import Path
from urllib.parse import urlsplit

from src.paths import DATA_ROOT


EDGE_LOCATIONS = (
    Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
    / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
    / "Microsoft/Edge/Application/msedge.exe",
)
_ATTACHED_INPUT_THREADS: dict[int, tuple[int, int]] = {}


def persistent_edge_profile(config: dict) -> Path:
    configured = str(config.get("edge_profile_path", "")).strip()
    return Path(configured).expanduser().resolve() if configured else DATA_ROOT / "runtime" / "edge-cdp-profile"


def find_edge() -> Path:
    for candidate in EDGE_LOCATIONS:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("未找到 Microsoft Edge，请确认 Edge 已安装。")


def build_edge_command(url: str, profile: Path, port: int = 9222, *, app_mode: bool = False) -> list[str]:
    parsed = urlsplit(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("平台地址无效，请填写 http 或 https 地址。")
    command = [
        str(find_edge()),
        f"--remote-debugging-port={int(port)}",
        f"--user-data-dir={profile.resolve()}",
    ]
    if app_mode:
        command.append(f"--app={url.strip()}")
    else:
        command.extend(("--new-window", url.strip()))
    return command


def _spawn(command: list[str]) -> None:
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


def open_persistent_edge(url: str, config: dict) -> Path:
    profile = persistent_edge_profile(config)
    profile.mkdir(parents=True, exist_ok=True)
    command = build_edge_command(url, profile, int(config.get("edge_debug_port", 9222)))
    _spawn(command)
    return profile


def _process_image(pid: int) -> str:
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def edge_window_handles() -> list[tuple[int, str]]:
    if os.name != "nt":
        return []
    user32 = ctypes.windll.user32
    windows: list[tuple[int, str]] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def collect(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        class_name = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(hwnd, class_name, len(class_name))
        if not class_name.value.startswith("Chrome_WidgetWin_"):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not _process_image(pid.value).lower().endswith("\\msedge.exe"):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, len(title))
        windows.append((int(hwnd), title.value))
        return True

    user32.EnumWindows(collect, 0)
    return windows


def launch_embedded_edge(url: str, config: dict) -> tuple[Path, set[int]]:
    profile = persistent_edge_profile(config)
    profile.mkdir(parents=True, exist_ok=True)
    previous = {handle for handle, _ in edge_window_handles()}
    command = build_edge_command(
        url,
        profile,
        int(config.get("edge_debug_port", 9222)),
        app_mode=True,
    )
    _spawn(command)
    return profile, previous


def find_embeddable_edge_window(previous: set[int]) -> int | None:
    candidates = [(handle, title) for handle, title in edge_window_handles() if handle not in previous]
    preferred = [item for item in candidates if "点众智投" in item[1]]
    return (preferred or candidates)[-1][0] if candidates else None


def prepare_edge_window_for_embedding(handle: int) -> None:
    if os.name != "nt":
        return
    user32 = ctypes.windll.user32
    get_style = user32.GetWindowLongPtrW
    set_style = user32.SetWindowLongPtrW
    get_style.restype = ctypes.c_ssize_t
    set_style.restype = ctypes.c_ssize_t
    style = get_style(handle, -16)
    window_chrome = 0x00C00000 | 0x00040000 | 0x00020000 | 0x00010000 | 0x00080000
    style = (style & ~window_chrome) | 0x40000000
    set_style(handle, -16, style)
    user32.SetWindowPos(handle, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)


def _edge_input_window(handle: int) -> int:
    if os.name != "nt":
        return handle
    user32 = ctypes.windll.user32
    candidates: list[tuple[int, int]] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def collect(hwnd, _):
        class_name = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(hwnd, class_name, len(class_name))
        if class_name.value == "Chrome_RenderWidgetHostHWND" and user32.IsWindowVisible(hwnd):
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            area = max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
            candidates.append((area, int(hwnd)))
        return True

    user32.EnumChildWindows(handle, collect, 0)
    return max(candidates, default=(0, handle))[1]


def focus_edge_window(handle: int) -> bool:
    if os.name != "nt" or not handle:
        return False
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    target_thread = user32.GetWindowThreadProcessId(handle, None)
    current_thread = kernel32.GetCurrentThreadId()
    if target_thread and target_thread != current_thread and handle not in _ATTACHED_INPUT_THREADS:
        if user32.AttachThreadInput(current_thread, target_thread, True):
            _ATTACHED_INPUT_THREADS[handle] = (current_thread, target_thread)
    root = user32.GetAncestor(handle, 2) or handle
    user32.SetForegroundWindow(root)
    user32.SetActiveWindow(handle)
    input_window = _edge_input_window(handle)
    focused = user32.SetFocus(input_window)
    ctypes.windll.imm32.ImmAssociateContextEx(input_window, 0, 0x10)
    return bool(focused or user32.GetFocus() == input_window)


def release_edge_input(handle: int) -> None:
    if os.name != "nt":
        return
    threads = _ATTACHED_INPUT_THREADS.pop(handle, None)
    if threads:
        ctypes.windll.user32.AttachThreadInput(threads[0], threads[1], False)
