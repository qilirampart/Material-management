from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter, sleep
from typing import Any, Callable
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import requests

from src.download_support import ApiConfigService
from src.download_support import DOWNLOADER_CONFIG_PATH
from src.media import FFmpegError, ensure_video_has_decodable_frame, merge_av_streams
from src.vendor.failover import FailoverRouter
from logging import getLogger as get_logger
from src.download_support import build_download_output_path

ProgressCallback = Callable[[int, int], None]
CancelCallback = Callable[[], bool]

_CONFIG_PATH = DOWNLOADER_CONFIG_PATH
_DEFAULT_CONFIG = {
    "enabled": True,
    "timeout_seconds": 45,
    "stream_read_timeout_seconds": 20,
    "slow_retry_enabled": True,
    "slow_retry_probe_seconds": 12,
    "slow_retry_probe_bytes": 5242880,
    "slow_retry_min_kbps": 600,
    "slow_retry_required_hits": 2,
    "slow_retry_max_wait_seconds": 24,
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
}
_URL_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_AWEME_ID_PATTERN = re.compile(r"/video/(\d+)")


class DouyinDownloadError(RuntimeError):
    pass


class _SlowDownloadCandidateError(DouyinDownloadError):
    pass


@dataclass
class DouyinDownloadResult:
    share_url: str
    parser_url: str
    video_url: str
    local_path: str
    title: str | None = None
    author: str | None = None


class DouyinDownloadService:
    def __init__(self) -> None:
        self._config: dict[str, Any] | None = None
        self._api_config_service = ApiConfigService()
        self._failover_router = FailoverRouter("douyin_parser", logger_name=__name__)
        self._logger = get_logger(__name__)

    def download_from_text(
        self,
        text: str,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> DouyinDownloadResult:
        share_url = self.extract_share_url(text)
        if not share_url:
            raise DouyinDownloadError("未识别到有效的抖音分享链接，请粘贴包含 https:// 的完整文本。")

        title: str | None = None
        author: str | None = None

        try:
            payload, parser_url = self._resolve_share_url(share_url, should_cancel=should_cancel)
            title = self._extract_text(payload, ("title", "desc", "aweme_id"))
            author = self._extract_text(payload, ("author", "nickname", "sec_uid"))
            video_urls = self._extract_video_urls(payload)
        except DouyinDownloadError as exc:
            parser_error = str(exc).strip() or "unknown parser error"
            self._logger.warning(
                "Douyin share url resolution failed before media download. share_url=%s error=%s",
                share_url,
                parser_error,
            )
            try:
                return self._download_via_browser_fallback(
                    share_url,
                    title=title,
                    author=author,
                    progress_callback=progress_callback,
                    should_cancel=should_cancel,
                )
            except DouyinDownloadError as fallback_exc:
                self._logger.warning(
                    "Douyin browser fallback failed. share_url=%s error=%s",
                    share_url,
                    fallback_exc,
                )
                detail = f"{parser_error}锛涙祻瑙堝櫒鍏滃簳澶辫触: {fallback_exc}"
                hint = self._download_failure_hint(detail, share_url=share_url)
                broken_message = """
                    f"涓嬭浇瑙嗛澶辫触锛屾姈闊抽摼鎺ヨВ鏋愬拰娴忚鍣ㄥ厹搴曢兘鏈垚鍔熴€倇detail}{hint}"
"""
                raise DouyinDownloadError(
                    "Failed to download Douyin video after parser and browser fallback both failed. details: "
                    + detail
                    + hint
                ) from fallback_exc

        errors: list[str] = []
        for index, video_url in enumerate(video_urls, start=1):
            self._check_cancelled(should_cancel)
            suffix = self._guess_suffix(video_url)
            local_path = build_download_output_path(title or "douyin_video", suffix=suffix)
            allow_slow_retry = index < len(video_urls)
            try:
                final_media_url = self._download_file(
                    video_url,
                    local_path,
                    progress_callback=progress_callback,
                    should_cancel=should_cancel,
                    allow_slow_retry=allow_slow_retry,
                )
                self._ensure_decodable_video_download(local_path)
                return DouyinDownloadResult(
                    share_url=share_url,
                    parser_url=parser_url,
                    video_url=final_media_url or video_url,
                    local_path=str(local_path),
                    title=title,
                    author=author,
                )
            except DouyinDownloadError as exc:
                if should_cancel is not None and should_cancel():
                    raise
                errors.append(f"候选链接 {index}: {exc}")

        detail = "；".join(errors[:3])
        if len(errors) > 3:
            detail += "；其余候选链接也已失败"
        try:
            return self._download_via_browser_fallback(
                share_url,
                title=title,
                author=author,
                progress_callback=progress_callback,
                should_cancel=should_cancel,
            )
        except DouyinDownloadError as exc:
            if should_cancel is not None and should_cancel():
                raise
            detail = f"{detail}；浏览器兜底失败: {exc}" if detail else f"浏览器兜底失败: {exc}"
        hint = self._download_failure_hint(detail, share_url=share_url)
        raise DouyinDownloadError(f"下载视频失败，所有候选直链均不可用。{detail}{hint}")

    def _download_via_browser_fallback(
        self,
        share_url: str,
        *,
        title: str | None = None,
        author: str | None = None,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> DouyinDownloadResult:
        self._check_cancelled(should_cancel)
        payload, parser_url = self._resolve_share_url_via_browser(share_url, should_cancel=should_cancel)
        media_url = str(payload.get("media_url") or payload.get("mediaUrl") or "").strip()
        audio_url = str(payload.get("audio_url") or payload.get("audioUrl") or "").strip()
        if not media_url:
            raise DouyinDownloadError("浏览器已打开页面，但没有拿到可下载的视频地址")

        resolved_title = title or self._clean_browser_title(str(payload.get("title") or "")) or None
        suffix = self._guess_suffix(media_url)
        local_path = build_download_output_path(resolved_title or "douyin_video", suffix=suffix)
        final_media_url = self._download_file(
            media_url,
            local_path,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
            allow_slow_retry=False,
        )
        if audio_url:
            self._merge_browser_audio_stream(
                local_path,
                audio_url,
                progress_callback=progress_callback,
                should_cancel=should_cancel,
            )
        else:
            self._logger.warning(
                "Douyin browser fallback did not expose an audio stream. share_url=%s",
                share_url,
            )
        self._ensure_decodable_video_download(local_path)
        self._logger.info("Douyin browser fallback download completed. path=%s", local_path)
        return DouyinDownloadResult(
            share_url=share_url,
            parser_url=parser_url,
            video_url=final_media_url or media_url,
            local_path=str(local_path),
            title=resolved_title,
            author=author,
        )

    def _resolve_share_url_via_browser(
        self,
        share_url: str,
        should_cancel: CancelCallback | None = None,
    ) -> tuple[dict[str, Any], str]:
        self._check_cancelled(should_cancel)
        fd, output_path_text = tempfile.mkstemp(prefix="douyin_browser_probe_", suffix=".json")
        os.close(fd)
        output_path = Path(output_path_text)
        # Douyin may spend several seconds running its anti-bot bootstrap before
        # the player emits the signed media request. Keep the parent process
        # alive longer than the probe itself so a valid result is not discarded.
        timeout = max(75.0, float(self.load_config().get("timeout_seconds", 45)) + 30.0)
        command = self._browser_probe_command(share_url, output_path)

        self._logger.info(
            "Starting Douyin browser fallback. share_url=%s runtime=%s timeout=%.0fs",
            share_url,
            command[0],
            timeout,
        )
        try:
            completed = subprocess.run(
                command,
                cwd=str(self._project_root()),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                **self._hidden_process_kwargs(),
            )
        except subprocess.TimeoutExpired as exc:
            output_path.unlink(missing_ok=True)
            raise DouyinDownloadError(
                self._friendly_browser_fallback_error(
                    "Timed out while waiting for the browser to expose a Douyin media URL.",
                    share_url=share_url,
                )
            ) from exc
        except OSError as exc:
            output_path.unlink(missing_ok=True)
            raise DouyinDownloadError(
                f"浏览器兜底进程启动失败: {exc}\n\n"
                "请先确认当前设备的系统浏览器能正常访问抖音链接。"
            ) from exc
        finally:
            self._check_cancelled(should_cancel)

        payload: dict[str, Any] | None = None
        try:
            if output_path.exists() and output_path.stat().st_size > 0:
                loaded = json.loads(output_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    payload = loaded
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Failed to read Douyin browser probe output. path=%s error=%s", output_path, exc)
        finally:
            output_path.unlink(missing_ok=True)

        if not payload:
            stdout = (completed.stdout or "").strip()
            stderr = (completed.stderr or "").strip()
            detail = stderr or stdout or f"exit_code={completed.returncode}"
            raise DouyinDownloadError(
                self._friendly_browser_fallback_error(
                    f"浏览器解析没有返回结果: {detail[:500]}",
                    share_url=share_url,
                )
            )

        if completed.returncode != 0 or not payload.get("ok", False):
            detail = str(payload.get("error") or completed.stderr or completed.stdout or "unknown error").strip()
            raise DouyinDownloadError(
                self._friendly_browser_fallback_error(detail[:500] or "浏览器解析失败", share_url=share_url)
            )

        media_url = str(payload.get("media_url") or "").strip()
        if not media_url:
            raise DouyinDownloadError(
                "浏览器兜底已打开页面，但没有拿到可下载的视频地址。\n\n"
                "如果你在系统浏览器里能打开该抖音链接，但这里仍然失败，请记录当前页面状态后反馈。"
            )

        self._logger.info(
            "Resolved Douyin media url via browser. source=%s video_host=%s audio_host=%s",
            payload.get("source"),
            urlsplit(media_url).netloc,
            urlsplit(str(payload.get("audio_url") or "")).netloc or "none",
        )
        return payload, "browser://douyin-current-src"

    def _merge_browser_audio_stream(
        self,
        video_path: Path,
        audio_url: str,
        *,
        progress_callback: ProgressCallback | None,
        should_cancel: CancelCallback | None,
    ) -> None:
        self._check_cancelled(should_cancel)
        fd, audio_path_text = tempfile.mkstemp(prefix="douyin_audio_", suffix=".m4a")
        os.close(fd)
        audio_path = Path(audio_path_text)
        merged_path = video_path.with_name(f"{video_path.stem}_merged.mp4")
        try:
            self._download_file(
                audio_url,
                audio_path,
                progress_callback=progress_callback,
                should_cancel=should_cancel,
                allow_slow_retry=False,
            )
            merge_av_streams(video_path, audio_path, merged_path)
            merged_path.replace(video_path)
            self._logger.info("Merged Douyin browser video and audio streams. path=%s", video_path)
        except (DouyinDownloadError, FFmpegError) as exc:
            merged_path.unlink(missing_ok=True)
            raise DouyinDownloadError(f"浏览器已获取音频流，但合并音视频失败: {exc}") from exc
        finally:
            audio_path.unlink(missing_ok=True)

    @classmethod
    def _browser_probe_command(cls, share_url: str, output_path: Path) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--probe-douyin-video-url", share_url, str(output_path)]

        project_root = cls._project_root()
        python_executable = cls._python_executable()
        return [
            python_executable,
            "-m",
            "src.vendor.browser_probe",
            share_url,
            str(output_path),
        ]

    @staticmethod
    def _project_root() -> Path:
        return Path(__file__).resolve().parents[2]

    @classmethod
    def _python_executable(cls) -> str:
        project_root = cls._project_root()
        executable_name = "python.exe" if os.name == "nt" else "python"
        candidates = [
            Path(sys.executable),
            project_root / ".venv" / "Scripts" / executable_name,
            project_root.parent / ".venv" / "Scripts" / executable_name,
            project_root.parent.parent / ".venv" / "Scripts" / executable_name,
        ]
        path_python = shutil.which("python")
        if path_python:
            candidates.append(Path(path_python))

        seen: set[str] = set()
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            key = str(resolved).lower()
            if key in seen or not resolved.exists():
                continue
            seen.add(key)
            if cls._has_probe_runtime_dependencies(resolved):
                return str(resolved)
        return sys.executable

    @classmethod
    def _has_probe_runtime_dependencies(cls, executable: Path) -> bool:
        """Avoid a partial venv that re-launches main.py and exits too early."""
        try:
            completed = subprocess.run(
                [str(executable), "-c", "import PySide6, requests, openpyxl"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
                **cls._hidden_process_kwargs(),
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return completed.returncode == 0

    @staticmethod
    def _hidden_process_kwargs() -> dict[str, object]:
        kwargs: dict[str, object] = {}
        if os.name != "nt":
            return kwargs

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if creationflags:
            kwargs["creationflags"] = creationflags

        startupinfo_factory = getattr(subprocess, "STARTUPINFO", None)
        if startupinfo_factory is not None:
            startupinfo = startupinfo_factory()
            startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
            startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
            kwargs["startupinfo"] = startupinfo
        return kwargs

    @staticmethod
    def _clean_browser_title(title: str) -> str:
        cleaned = (title or "").strip()
        for marker in (" - 抖音", "_哔哩哔哩", " | "):
            if marker in cleaned:
                cleaned = cleaned.split(marker, 1)[0].strip()
        return cleaned[:80]

    @staticmethod
    def _browser_access_hint(share_url: str) -> str:
        return (
            "请先在当前设备的系统浏览器里打开这个抖音链接确认能正常访问：\n"
            f"{share_url}\n\n"
            "如果系统浏览器也打不开，通常是当前网络、代理或访问限制导致，不是软件本身故障。"
        )

    def _friendly_browser_fallback_error(self, detail: str, *, share_url: str) -> str:
        message = str(detail or "").strip()
        lowered = message.lower()
        hint = self._browser_access_hint(share_url)

        if "browser fallback could not load the douyin page" in lowered:
            return f"浏览器兜底未能加载抖音页面。\n\n{hint}"
        if "timed out while waiting for the browser to expose a douyin media url" in lowered:
            return f"浏览器兜底解析超时，未能拿到视频地址。\n\n{hint}"
        if "browser probe did not return a media url" in lowered:
            return f"浏览器兜底没有拿到视频地址。\n\n{hint}"
        if "qt webengine is not available" in lowered:
            return "当前运行环境缺少浏览器内核组件，无法执行抖音页面兜底解析。"
        if "浏览器解析没有返回结果" in message:
            return f"{message}\n\n{hint}"
        return message

    def _download_failure_hint(self, detail: str, *, share_url: str) -> str:
        lowered = str(detail or "").lower()
        if (
            "browser fallback could not load the douyin page" in lowered
            or "浏览器兜底未能加载抖音页面" in lowered
            or "浏览器兜底解析超时" in lowered
            or "浏览器兜底没有拿到视频地址" in lowered
        ):
            return f"\n\n{self._browser_access_hint(share_url)}"
        return ""

    def download_from_resolved_media(
        self,
        text: str,
        media_url: str,
        *,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> DouyinDownloadResult:
        share_url = self.extract_share_url(text)
        title: str | None = None
        author: str | None = None

        if share_url:
            try:
                payload = self._resolve_share_url_locally(share_url, should_cancel=should_cancel)
                title = self._extract_text(payload, ("title", "desc", "aweme_id"))
                author = self._extract_text(payload, ("author", "nickname", "sec_uid"))
            except Exception:  # noqa: BLE001
                title = None
                author = None

        suffix = self._guess_suffix(media_url)
        local_path = build_download_output_path(title or "douyin_video", suffix=suffix)
        final_media_url = self._download_file(
            media_url,
            local_path,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
            allow_slow_retry=False,
        )
        self._ensure_decodable_video_download(local_path)
        return DouyinDownloadResult(
            share_url=share_url or media_url,
            parser_url="browser://douyin-current-src",
            video_url=final_media_url or media_url,
            local_path=str(local_path),
            title=title,
            author=author,
        )

    @staticmethod
    def extract_share_url(text: str) -> str | None:
        if not text:
            return None
        match = _URL_PATTERN.search(text)
        return match.group(0).rstrip(".,);") if match else None

    def load_config(self) -> dict[str, Any]:
        if self._config is not None:
            return self._config

        if not _CONFIG_PATH.exists():
            _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            _CONFIG_PATH.write_text(
                json.dumps(_DEFAULT_CONFIG, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._config = dict(_DEFAULT_CONFIG)
            return self._config

        with open(_CONFIG_PATH, encoding="utf-8") as handle:
            loaded = json.load(handle)

        merged = dict(_DEFAULT_CONFIG)
        merged.update(loaded)
        self._config = merged
        return self._config

    def _resolve_share_url(
        self,
        share_url: str,
        should_cancel: CancelCallback | None = None,
    ) -> tuple[Any, str]:
        config = self.load_config()
        if not config.get("enabled", True):
            raise DouyinDownloadError("下载能力已被禁用，请检查 runtime/downloader_config.json。")

        builtin_errors: list[str] = []
        self._check_cancelled(should_cancel)
        try:
            payload = self._resolve_share_url_locally(share_url, should_cancel=should_cancel)
            self._logger.info("Resolved Douyin share url locally. share_url=%s", share_url)
            return payload, "builtin://douyin-share-page"
        except Exception as exc:  # noqa: BLE001
            error_message = str(exc)
            self._logger.warning("Local Douyin resolver failed. share_url=%s error=%s", share_url, error_message)
            builtin_errors.append(f"builtin: {error_message}")

        api_config = self._api_config_service.load_config()
        parser_section = api_config.get("douyin_parser", {})
        if not parser_section.get("enabled", True):
            raise DouyinDownloadError("抖音解析 API 已被禁用，请检查 runtime/api_config.json。")
        parser_providers = self._api_config_service.list_douyin_parser_providers()
        if not parser_providers:
            raise DouyinDownloadError("没有配置可用的抖音解析 API，请检查 runtime/api_config.json。")

        failover_policy = parser_section.get("failover", {})
        failure_threshold = max(1, int(failover_policy.get("failure_threshold", 1) or 1))
        cooldown_seconds = max(0, int(failover_policy.get("cooldown_seconds", 300) or 300))

        for provider in self._failover_router.ordered_candidates(
            parser_providers,
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
        ):
            self._check_cancelled(should_cancel)
            provider_name = str(provider.get("name") or "Douyin Parser")
            try:
                payload, parser_url = self._resolve_share_url_via_service(
                    share_url,
                    provider=provider,
                    should_cancel=should_cancel,
                )
            except Exception as exc:  # noqa: BLE001
                error_message = str(exc)
                self._logger.warning(
                    "Douyin parser failed. provider=%s share_url=%s error=%s",
                    provider_name,
                    share_url,
                    error_message,
                )
                self._failover_router.record_failure(
                    provider,
                    error_message,
                    failure_threshold=failure_threshold,
                    cooldown_seconds=cooldown_seconds,
                )
                builtin_errors.append(f"{provider_name}: {error_message}")
                continue

            self._failover_router.record_success(provider)
            self._logger.info(
                "Resolved Douyin share url via parser provider=%s parser_url=%s",
                provider_name,
                parser_url,
            )
            return payload, parser_url

        raise DouyinDownloadError("解析抖音分享链接失败: " + "；".join(builtin_errors))

    def _resolve_share_url_locally(
        self,
        share_url: str,
        should_cancel: CancelCallback | None = None,
    ) -> dict[str, Any]:
        self._check_cancelled(should_cancel)
        expanded_url = self._expand_short_link(share_url)
        aweme_id = self._extract_aweme_id(expanded_url)
        if not aweme_id:
            raise DouyinDownloadError("本地解析未能从短链跳转结果中识别作品 ID。")

        self._check_cancelled(should_cancel)
        share_page_url = f"https://www.iesdouyin.com/share/video/{aweme_id}/"
        response = self._session().get(
            share_page_url,
            headers=self._mobile_headers(),
            timeout=float(self.load_config().get("timeout_seconds", 45)),
            allow_redirects=True,
        )
        response.raise_for_status()
        html = response.text

        video_id = self._extract_json_string(html, "uri", anchor="play_addr")
        if not video_id:
            video_id = self._extract_json_string(html, "uri", anchor="play_api")
        if not video_id:
            raise DouyinDownloadError("本地解析未能从分享页中提取视频 ID。")

        title = self._extract_json_string(html, "desc")
        author = self._extract_json_string(html, "nickname")
        url_list = self._extract_url_list_after_anchor(html, "play_addr")
        download_url = self._extract_json_string(html, "download_url")

        candidates: list[str] = []
        candidates.append(f"https://www.iesdouyin.com/aweme/v1/play/?video_id={quote(video_id)}&ratio=1080p&line=0")
        candidates.append(f"https://www.iesdouyin.com/aweme/v1/play/?video_id={quote(video_id)}&ratio=720p&line=0")

        for url in url_list:
            candidates.append(url.replace("/playwm/", "/play/"))
            candidates.append(url)

        if download_url:
            candidates.append(download_url)

        unique_candidates: list[str] = []
        seen: set[str] = set()
        for url in candidates:
            if not url or not url.startswith(("http://", "https://")):
                continue
            if url in seen:
                continue
            seen.add(url)
            unique_candidates.append(url)

        return {
            "aweme_id": aweme_id,
            "title": title,
            "author": author,
            "video_id": video_id,
            "video_url": unique_candidates[0] if unique_candidates else "",
            "play_urls": unique_candidates,
            "share_page_url": share_page_url,
            "expanded_share_url": expanded_url,
        }

    def _resolve_share_url_via_service(
        self,
        share_url: str,
        *,
        provider: dict[str, Any],
        should_cancel: CancelCallback | None = None,
    ) -> tuple[Any, str]:
        self._check_cancelled(should_cancel)
        parser_url = self._build_parser_url(str(provider.get("base_url") or "").strip(), share_url)
        response = self._session().get(
            parser_url,
            headers=self._default_headers(),
            timeout=float(self.load_config().get("timeout_seconds", 45)),
            allow_redirects=True,
        )
        response.raise_for_status()
        body = response.text.strip()

        try:
            return json.loads(body), parser_url
        except json.JSONDecodeError:
            if body.startswith(("http://", "https://")):
                return {"video_url": body}, parser_url
            raise DouyinDownloadError("外部解析服务返回的内容不是可用的 JSON 或视频直链。")

    @staticmethod
    def _build_parser_url(base_url: str, share_url: str) -> str:
        if not base_url:
            raise DouyinDownloadError("解析服务地址为空，请检查 runtime/downloader_config.json。")

        parts = urlsplit(base_url)
        query = parse_qsl(parts.query, keep_blank_values=True)
        query = [(key, value) for key, value in query if key.lower() not in {"url", "data"}]
        query.append(("url", share_url))
        query.append(("data", ""))
        rebuilt_query = urlencode(query, doseq=True)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, rebuilt_query, parts.fragment))

    def _expand_short_link(self, share_url: str) -> str:
        response = self._session().get(
            share_url,
            headers=self._default_headers(),
            timeout=float(self.load_config().get("timeout_seconds", 45)),
            allow_redirects=True,
        )
        response.raise_for_status()
        return response.url

    @staticmethod
    def _extract_aweme_id(expanded_url: str) -> str | None:
        match = _AWEME_ID_PATTERN.search(expanded_url)
        return match.group(1) if match else None

    def _download_file(
        self,
        source_url: str,
        target_path: Path,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
        *,
        allow_slow_retry: bool = False,
    ) -> str:
        timeout = self._request_timeout(allow_slow_retry=allow_slow_retry)
        last_error: Exception | None = None

        header_variants = self._download_header_variants(source_url)
        for attempt_index, headers in enumerate(header_variants, start=1):
            self._check_cancelled(should_cancel)
            try:
                started_at = perf_counter()
                slow_probe_hits = 0
                with self._session().get(
                    source_url,
                    headers=headers,
                    timeout=timeout,
                    allow_redirects=True,
                    stream=True,
                ) as response, open(target_path, "wb") as handle:
                    response.raise_for_status()
                    total = int(response.headers.get("Content-Length") or 0)
                    downloaded = 0
                    if progress_callback is not None:
                        progress_callback(0, total)
                    stream = response.iter_content(chunk_size=1024 * 128)
                    first_chunk = next(stream, b"")
                    self._validate_media_probe(response.headers.get("Content-Type", ""), first_chunk, response.url)
                    if first_chunk:
                        handle.write(first_chunk)
                        downloaded += len(first_chunk)
                        if progress_callback is not None:
                            progress_callback(downloaded, total)
                        slow_probe_hits = self._raise_if_candidate_too_slow(
                            allow_slow_retry=allow_slow_retry,
                            started_at=started_at,
                            downloaded=downloaded,
                            total=total,
                            source_url=source_url,
                            slow_probe_hits=slow_probe_hits,
                        )
                    for chunk in stream:
                        self._check_cancelled(should_cancel)
                        if not chunk:
                            continue
                        handle.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback is not None:
                            progress_callback(downloaded, total)
                        slow_probe_hits = self._raise_if_candidate_too_slow(
                            allow_slow_retry=allow_slow_retry,
                            started_at=started_at,
                            downloaded=downloaded,
                            total=total,
                            source_url=source_url,
                            slow_probe_hits=slow_probe_hits,
                        )
                final_url = response.url or source_url
                elapsed_seconds = max(perf_counter() - started_at, 0.001)
                self._logger.info(
                    "Douyin media download finished. host=%s bytes=%s elapsed=%.2fs avg_kbps=%.1f url=%s",
                    urlsplit(final_url).netloc,
                    downloaded,
                    elapsed_seconds,
                    downloaded / 1024 / elapsed_seconds,
                    final_url,
                )
                return final_url
            except _SlowDownloadCandidateError as exc:
                last_error = exc
                if target_path.exists():
                    target_path.unlink(missing_ok=True)
                self._logger.info(
                    "Douyin media candidate abandoned due to slow speed; switching to next media candidate. url=%s error=%s",
                    source_url,
                    exc,
                )
                break
            except requests.HTTPError as exc:
                last_error = exc
                if target_path.exists():
                    target_path.unlink(missing_ok=True)
                status_code = exc.response.status_code if exc.response is not None else None
                self._logger.warning(
                    "Douyin media request rejected. url=%s status=%s",
                    source_url,
                    status_code,
                )
                if status_code not in {401, 403, 429}:
                    break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if target_path.exists():
                    target_path.unlink(missing_ok=True)
                self._logger.warning("Douyin media download attempt failed. url=%s error=%s", source_url, exc)
                if attempt_index < len(header_variants) and isinstance(exc, requests.ConnectionError):
                    retry_delay = min(2.0, 0.6 * attempt_index)
                    self._logger.info(
                        "Douyin media connection failed; retrying in %.1fs. host=%s attempt=%s/%s",
                        retry_delay,
                        urlsplit(source_url).netloc,
                        attempt_index,
                        len(header_variants),
                    )
                    sleep(retry_delay)

        if target_path.exists():
            target_path.unlink(missing_ok=True)

        if isinstance(last_error, requests.HTTPError):
            status_code = last_error.response.status_code if last_error.response is not None else "unknown"
            raise DouyinDownloadError(f"直链请求被拒绝，HTTP {status_code}") from last_error
        if last_error is not None:
            raise DouyinDownloadError(f"下载直链失败: {last_error}") from last_error
        raise DouyinDownloadError("下载直链失败，未获取到可用响应。")

    def _request_timeout(self, *, allow_slow_retry: bool) -> float | tuple[float, float]:
        config = self.load_config()
        timeout = max(5.0, float(config.get("timeout_seconds", 45) or 45))
        connect_timeout = min(timeout, 10.0)
        if not allow_slow_retry:
            return (connect_timeout, timeout)

        read_timeout = max(
            8.0,
            min(
                timeout,
                float(
                    config.get(
                        "stream_read_timeout_seconds",
                        _DEFAULT_CONFIG["stream_read_timeout_seconds"],
                    )
                    or timeout
                ),
            ),
        )
        return (connect_timeout, read_timeout)

    def _default_headers(self) -> dict[str, str]:
        config = self.load_config()
        return {
            "User-Agent": str(config.get("user_agent", _DEFAULT_CONFIG["user_agent"])),
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Connection": "keep-alive",
        }

    def _mobile_headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
                "Mobile/15E148 Safari/604.1"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": "https://www.douyin.com/",
        }

    def _download_header_variants(self, source_url: str) -> list[dict[str, str]]:
        host = urlsplit(source_url).netloc
        base = self._default_headers()
        variants = [
            {
                **base,
                "Referer": "https://www.douyin.com/",
                "Origin": "https://www.douyin.com",
            },
            {
                **base,
                "Referer": "https://www.douyin.com/",
                "Origin": "https://www.douyin.com",
                "Range": "bytes=0-",
            },
            {
                **base,
                "Referer": "https://www.douyin.com/",
                "Origin": "https://www.douyin.com",
                "Range": "bytes=0-",
                "Host": host,
            },
            {
                **base,
                "Range": "bytes=0-",
                "Host": host,
            },
            {
                **base,
                "Host": host,
            },
            base,
        ]

        unique_variants: list[dict[str, str]] = []
        seen: set[tuple[tuple[str, str], ...]] = set()
        for headers in variants:
            marker = tuple(sorted(headers.items()))
            if marker in seen:
                continue
            seen.add(marker)
            unique_variants.append(headers)
        return unique_variants

    @staticmethod
    def _ensure_decodable_video_download(target_path: Path) -> None:
        try:
            ensure_video_has_decodable_frame(target_path)
        except FFmpegError as exc:
            target_path.unlink(missing_ok=True)
            raise DouyinDownloadError(
                "抖音返回的视频文件无法正常解码，可能是受保护内容或广告解锁视频，当前软件暂时无法下载可用源文件。"
            ) from exc

    def _extract_video_urls(self, payload: Any) -> list[str]:
        candidates: list[tuple[float, int, str]] = []
        for key_path, value in self._walk(payload):
            if not isinstance(value, str):
                continue
            url = value.strip()
            if not url.startswith(("http://", "https://")):
                continue
            score = self._score_candidate(key_path, url)
            if score > 0:
                quality = self._candidate_quality_hint(payload, key_path, url)
                candidates.append((quality, score, url))

        if not candidates:
            raise DouyinDownloadError("解析结果中没有找到可用的视频直链。")

        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        ordered_urls: list[str] = []
        seen: set[str] = set()
        for _, _, url in candidates:
            if url in seen:
                continue
            seen.add(url)
            ordered_urls.append(url)
        return ordered_urls

    @classmethod
    def _candidate_quality_hint(
        cls,
        payload: Any,
        key_path: tuple[str, ...],
        url: str,
    ) -> float:
        current = payload
        ancestors: list[Any] = [payload]
        for token in key_path[:-1]:
            try:
                current = current[int(token)] if isinstance(current, list) else current[token]
            except (IndexError, KeyError, TypeError, ValueError):
                break
            ancestors.append(current)

        for value in reversed(ancestors):
            if not isinstance(value, dict):
                continue
            hint = cls._mapping_quality_hint(value)
            if hint > 0:
                return hint
        return cls._text_quality_hint(url)

    @classmethod
    def _mapping_quality_hint(cls, value: dict[str, Any]) -> float:
        bitrate = 0.0
        width = 0.0
        height = 0.0
        text_hint = 0.0
        for key, raw in value.items():
            lowered = str(key).lower().replace("-", "_")
            if lowered in {"bit_rate", "bitrate", "video_bitrate", "data_rate"}:
                try:
                    number = float(raw)
                except (TypeError, ValueError):
                    number = 0.0
                bitrate = max(bitrate, number / 1000 if number > 100_000 else number)
            elif lowered in {"width", "video_width"}:
                try:
                    width = max(width, float(raw))
                except (TypeError, ValueError):
                    pass
            elif lowered in {"height", "video_height"}:
                try:
                    height = max(height, float(raw))
                except (TypeError, ValueError):
                    pass
            elif lowered in {"gear_name", "quality", "quality_type", "resolution", "ratio"}:
                text_hint = max(text_hint, cls._text_quality_hint(str(raw)))
        resolution_hint = width * height / 1000 if width and height else 0.0
        return max(bitrate, resolution_hint, text_hint)

    @staticmethod
    def _text_quality_hint(value: str) -> float:
        text = str(value).lower()
        dimensions = re.search(r"(\d{3,4})\s*[x×]\s*(\d{3,4})", text)
        if dimensions:
            return int(dimensions.group(1)) * int(dimensions.group(2)) / 1000
        progressive = re.search(r"(?<!\d)(\d{3,4})p(?!\d)", text)
        return float(progressive.group(1)) if progressive else 0.0

    def _extract_text(self, payload: Any, preferred_keys: tuple[str, ...]) -> str | None:
        for key_path, value in self._walk(payload):
            if not isinstance(value, str):
                continue
            lowered_path = ".".join(key_path).lower()
            if any(preferred in lowered_path for preferred in preferred_keys):
                candidate = value.strip()
                if candidate and not candidate.startswith("http"):
                    return candidate[:80]
        return None

    @staticmethod
    def _score_candidate(key_path: tuple[str, ...], url: str) -> int:
        lowered_path = ".".join(key_path).lower()
        lowered_url = url.lower()
        parsed = urlsplit(url)
        host = parsed.netloc.lower()
        path = parsed.path.lower()

        if "z.douyin.com" in host:
            return 0
        if any(token in host for token in ("douyin.com", "iesdouyin.com")) and (
            path.startswith("/video/") or "/share/video/" in path
        ):
            return 0

        if any(token in lowered_path for token in ("cover", "music", "avatar", "image", "images")):
            return 0

        score = 0
        if "video" in lowered_path:
            score += 30
        if any(token in lowered_path for token in ("nwm", "no_water", "nowater", "play", "play_addr", "url_list")):
            score += 25
        if lowered_url.endswith(".mp4"):
            score += 20
        if any(token in lowered_url for token in ("video", "play", "aweme")):
            score += 10
        if "watermark" in lowered_url or "playwm" in lowered_url:
            score -= 10
        return score

    @staticmethod
    def _validate_media_probe(content_type: str, head_bytes: bytes, response_url: str) -> None:
        if DouyinDownloadService._looks_like_html_response(content_type, head_bytes):
            raise DouyinDownloadError(f"Direct URL returned HTML instead of media: {response_url}")
        if not DouyinDownloadService._looks_like_video_response(content_type, head_bytes):
            raise DouyinDownloadError(f"Direct URL did not return playable MP4 media: {response_url}")

    @staticmethod
    def _looks_like_html_response(content_type: str, head_bytes: bytes) -> bool:
        lowered_type = (content_type or "").lower()
        if any(token in lowered_type for token in ("text/html", "application/xhtml", "application/json", "text/plain")):
            return True

        probe = (head_bytes or b"").lstrip().lower()
        if probe.startswith((b"<!doctype html", b"<html", b"<?xml")):
            return True
        if probe.startswith(b"{") and b"status_code" in probe[:64]:
            return True
        return False

    @staticmethod
    def _looks_like_video_response(content_type: str, head_bytes: bytes) -> bool:
        lowered_type = (content_type or "").lower()
        if lowered_type.startswith("video/"):
            return True
        probe = head_bytes or b""
        return b"ftyp" in probe[:32]

    def _raise_if_candidate_too_slow(
        self,
        *,
        allow_slow_retry: bool,
        started_at: float,
        downloaded: int,
        total: int,
        source_url: str,
        slow_probe_hits: int,
    ) -> int:
        if not allow_slow_retry:
            return 0

        config = self.load_config()
        if not config.get("slow_retry_enabled", True):
            return 0

        elapsed_seconds = max(perf_counter() - started_at, 0.001)
        avg_kbps = downloaded / 1024 / elapsed_seconds
        probe_seconds = max(1.0, float(config.get("slow_retry_probe_seconds", 12) or 12))
        probe_bytes = max(1024 * 1024, int(config.get("slow_retry_probe_bytes", 5 * 1024 * 1024) or 5 * 1024 * 1024))
        min_kbps = max(64.0, float(config.get("slow_retry_min_kbps", 600) or 600))
        required_hits = max(1, int(config.get("slow_retry_required_hits", 2) or 2))
        max_wait_seconds = max(
            probe_seconds,
            float(config.get("slow_retry_max_wait_seconds", _DEFAULT_CONFIG["slow_retry_max_wait_seconds"]) or probe_seconds),
        )

        if elapsed_seconds < probe_seconds:
            return 0
        if downloaded < probe_bytes and elapsed_seconds < max_wait_seconds:
            return 0
        if avg_kbps >= min_kbps:
            return 0

        if total > 0:
            completion_ratio = downloaded / total if total else 0.0
            remaining_bytes = max(total - downloaded, 0)
            if completion_ratio >= 0.7 or remaining_bytes < 2 * 1024 * 1024:
                return 0

        next_probe_hits = slow_probe_hits + 1
        if next_probe_hits < required_hits:
            self._logger.info(
                "Douyin media candidate slow probe hit %s/%s. avg_kbps=%.1f threshold=%.1f elapsed=%.1fs url=%s",
                next_probe_hits,
                required_hits,
                avg_kbps,
                min_kbps,
                elapsed_seconds,
                source_url,
            )
            return next_probe_hits

        raise _SlowDownloadCandidateError(
            f"avg speed {avg_kbps:.1f} KB/s below threshold {min_kbps:.1f} KB/s "
            f"after {elapsed_seconds:.1f}s with {next_probe_hits} slow probes, switching candidate: {source_url}"
        )

    @staticmethod
    def _walk(payload: Any, key_path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
        items: list[tuple[tuple[str, ...], Any]] = []
        if isinstance(payload, dict):
            for key, value in payload.items():
                items.extend(DouyinDownloadService._walk(value, key_path + (str(key),)))
            return items
        if isinstance(payload, list):
            for index, value in enumerate(payload):
                items.extend(DouyinDownloadService._walk(value, key_path + (str(index),)))
            return items
        items.append((key_path, payload))
        return items

    @staticmethod
    def _guess_suffix(video_url: str) -> str:
        path = urlsplit(video_url).path
        suffix = Path(path).suffix.lower()
        if suffix in {".mp4", ".mov", ".m4v"}:
            return suffix
        return ".mp4"

    @staticmethod
    def _decode_js_string(value: str) -> str:
        try:
            return json.loads(f'"{value}"')
        except Exception:  # noqa: BLE001
            return value.replace("\\/", "/").replace("\\u002F", "/")

    def _extract_json_string(self, text: str, key: str, *, anchor: str | None = None) -> str | None:
        search_text = text
        if anchor:
            anchor_index = text.find(anchor)
            if anchor_index != -1:
                search_text = text[anchor_index : anchor_index + 6000]
        pattern = rf'"{re.escape(key)}":"((?:\\.|[^"\\])*)"'
        match = re.search(pattern, search_text)
        if not match:
            return None
        value = self._decode_js_string(match.group(1)).strip()
        return value or None

    def _extract_url_list_after_anchor(self, text: str, anchor: str) -> list[str]:
        anchor_index = text.find(anchor)
        if anchor_index == -1:
            return []
        search_text = text[anchor_index : anchor_index + 12000]
        match = re.search(r'"url_list":\[(.*?)\]', search_text, re.S)
        if not match:
            return []

        urls: list[str] = []
        for raw in re.findall(r'"((?:\\.|[^"\\])*)"', match.group(1)):
            url = self._decode_js_string(raw).strip()
            if url.startswith(("http://", "https://")):
                urls.append(url)
        return urls

    @staticmethod
    def _check_cancelled(should_cancel: CancelCallback | None) -> None:
        if should_cancel is not None and should_cancel():
            raise DouyinDownloadError("下载已取消。")

    @staticmethod
    def _session() -> requests.Session:
        session = requests.Session()
        session.trust_env = False
        return session
