from __future__ import annotations

import json
import errno
import shutil
import tempfile
from pathlib import Path
from src.paths import DATA_ROOT

DOWNLOADER_CONFIG_PATH = DATA_ROOT / "runtime" / "downloader_config.json"


class ApiConfigService:
    """In-memory parser settings injected by Downloader; no source-project writes."""
    def __init__(self):
        self.data = {}

    def load_config(self):
        return self.data

    def list_douyin_parser_providers(self):
        return sorted([p for p in self.data.get("douyin_parser", {}).get("providers", [])
                       if p.get("enabled", True) and p.get("base_url")], key=lambda p: p.get("priority", 1))


def build_download_output_path(title, suffix=".mp4"):
    # Temporary paths are later validated and atomically promoted to the video-ID path.
    import os
    folder = DATA_ROOT / "runtime" / "downloads"
    folder.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix="douyin_", suffix=suffix, dir=str(folder))
    os.close(fd)
    return Path(filename)


class Downloader:
    def __init__(self, config):
        from src.vendor.douyin import DouyinDownloadService, _DEFAULT_CONFIG
        self.service = DouyinDownloadService()
        self.service._config = dict(_DEFAULT_CONFIG)
        settings = Path(config["downloader_config_path"])
        if settings.is_file():
            self.service._config.update(json.loads(settings.read_text(encoding="utf-8-sig")))
        settings = Path(config["parser_config_path"])
        if settings.is_file():
            data = json.loads(settings.read_text(encoding="utf-8-sig"))
            self.service._api_config_service.data = {"douyin_parser": data.get("douyin_parser", {})}

    def download(self, url, target):
        from src.media import validate_video
        from src.download_progress import DownloadProgress
        emit = getattr(self, 'on_event', None) or (lambda event: None)
        emit({'type': 'progress', 'stage': '解析视频链接'})
        result = self.service.download_from_text(url, progress_callback=DownloadProgress(emit))
        source = Path(result.local_path)
        staged = target.with_suffix(".part")
        try:
            emit({'type': 'progress', 'stage': '完整性校验'})
            meta = validate_video(source)
            emit({'type': 'progress', 'stage': '保存视频文件'})
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                source.replace(staged)
            except OSError as exc:
                if exc.errno != errno.EXDEV and getattr(exc, 'winerror', None) != 17:
                    raise
                shutil.copyfile(source, staged)
            staged.replace(target)
            return meta
        finally:
            staged.unlink(missing_ok=True)
            source.unlink(missing_ok=True)
