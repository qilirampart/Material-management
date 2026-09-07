"""One-time source migration; never reads credentials or changes the reference project."""
from pathlib import Path

source = Path(r"E:\点众\自动化工具\侵权巡检助手工作区\源码")
target = Path(__file__).resolve().parents[1] / "src" / "vendor"
target.mkdir(parents=True, exist_ok=True)
(target / "__init__.py").write_text('', encoding="utf-8")
files = {
    "app/services/douyin_download_service.py": "douyin.py",
    "app/services/douyin_browser_probe.py": "browser_probe.py",
    "app/utils/failover.py": "failover.py",
}
for old, new in files.items():
    text = (source / old).read_text(encoding="utf-8")
    text = text.replace('from app.services.api_config_service import ApiConfigService', 'from src.download_support import ApiConfigService')
    text = text.replace('from app.config.settings import DOWNLOADER_CONFIG_PATH', 'from src.download_support import DOWNLOADER_CONFIG_PATH')
    text = text.replace('from app.utils.ffmpeg import', 'from src.media import')
    text = text.replace('from app.utils.failover import', 'from src.vendor.failover import')
    text = text.replace('from app.utils.logger import get_logger', 'from logging import getLogger as get_logger')
    text = text.replace('from app.utils.paths import build_download_output_path', 'from src.download_support import build_download_output_path')
    text = text.replace('str(project_root / "main.py"),\n            "--probe-douyin-video-url",', '"-m",\n            "src.vendor.browser_probe",')
    (target / new).write_text(text, encoding="utf-8")
