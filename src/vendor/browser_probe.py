from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtWidgets import QApplication

try:
    from PySide6.QtWebEngineCore import (
        QWebEnginePage,
        QWebEngineProfile,
        QWebEngineUrlRequestInterceptor,
    )

    QT_WEBENGINE_AVAILABLE = True
except ImportError:
    QWebEnginePage = None  # type: ignore[assignment]
    QWebEngineProfile = None  # type: ignore[assignment]
    QWebEngineUrlRequestInterceptor = None  # type: ignore[assignment]
    QT_WEBENGINE_AVAILABLE = False


@dataclass
class DouyinBrowserProbeResult:
    page_url: str
    media_url: str
    audio_url: str = ""
    title: str = ""
    source: str = "browser"


class _DouyinMediaRequestInterceptor(QWebEngineUrlRequestInterceptor):
    media_requested = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._seen_urls: set[str] = set()

    def interceptRequest(self, info) -> None:  # type: ignore[override]
        url = info.requestUrl().toString().strip()
        if not looks_like_stream_url(url) or url in self._seen_urls:
            return
        self._seen_urls.add(url)
        self.media_requested.emit(url)


class _DouyinBrowserProbe(QObject):
    def __init__(self, url: str, *, timeout_ms: int = 25000) -> None:
        super().__init__()
        self._url = url
        self._timeout_ms = timeout_ms
        self._page = None
        self._profile = None
        self._interceptor = None
        self._finished = False
        self.result: DouyinBrowserProbeResult | None = None
        self.error: str | None = None
        self._video_url = ""
        self._audio_url = ""
        self._page_url = ""
        self._title = ""
        self._source = "browser"
        self._video_candidates: set[str] = set()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(600)
        self._poll_timer.timeout.connect(self._poll_page)

        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)

        # The player requests its video stream first and the AAC stream shortly
        # afterwards. Do not close the probe as soon as video is observed.
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.timeout.connect(self._finish_collected_streams)

    def start(self) -> None:
        if not QT_WEBENGINE_AVAILABLE:
            self._finish_failed("Qt WebEngine is not available.")
            return

        # A fresh profile prevents an old signed CDN URL or service-worker cache
        # from a prior probe being reused for the next short link.
        self._profile = QWebEngineProfile(self)
        try:
            cache_type = getattr(getattr(QWebEngineProfile, "HttpCacheType", None), "MemoryHttpCache", None)
            if cache_type is not None:
                self._profile.setHttpCacheType(cache_type)
            cookie_policy = getattr(
                getattr(QWebEngineProfile, "PersistentCookiesPolicy", None),
                "NoPersistentCookies",
                None,
            )
            if cookie_policy is not None:
                self._profile.setPersistentCookiesPolicy(cookie_policy)
            self._profile.setHttpUserAgent(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
            )
            self._profile.setHttpAcceptLanguage("zh-CN,zh;q=0.9,en;q=0.8")
        except Exception:
            pass

        self._page = QWebEnginePage(self._profile, self)
        self._interceptor = _DouyinMediaRequestInterceptor(self)
        self._interceptor.media_requested.connect(self._handle_media_url)
        try:
            self._profile.setUrlRequestInterceptor(self._interceptor)
        except Exception:
            try:
                self._page.setUrlRequestInterceptor(self._interceptor)
            except Exception:
                pass

        self._page.loadFinished.connect(self._on_load_finished)
        self._page.load(QUrl.fromUserInput(self._url))
        self._timeout_timer.start(self._timeout_ms)

        # Some Douyin pages keep streaming requests before loadFinished or delay
        # loadFinished. Polling early avoids waiting for the full document state.
        self._poll_timer.start()
        QTimer.singleShot(900, self._poll_page)

    def _on_load_finished(self, ok: bool) -> None:
        if self._finished:
            return
        if not ok:
            self._finish_failed("Browser fallback could not load the Douyin page.")
            return
        self._poll_page()

    def _poll_page(self) -> None:
        if self._finished or self._page is None:
            return
        self._page.runJavaScript(
            """
            (() => {
              const videos = Array.from(document.querySelectorAll("video"));
              for (const video of videos) {
                try {
                  video.muted = false;
                  video.defaultMuted = false;
                  video.volume = 0.01;
                  video.playsInline = true;
                  const playResult = video.play?.();
                  if (playResult && typeof playResult.catch === "function") {
                    playResult.catch(() => {});
                  }
                } catch (err) {}
              }
              const resources = performance.getEntriesByType("resource")
                .map((entry) => entry.name || "")
                .filter((url) => /douyinvod\.com|mime_type=(video|audio)|media-audio|aweme\/v1\/play/i.test(url));
              return {
                pageUrl: location.href || "",
                title: document.title || "",
                resources,
                videos: videos.map((video) => ({
                  mediaUrl: video.currentSrc || video.src || "",
                  readyState: video.readyState || 0,
                  duration: Number.isFinite(video.duration) ? video.duration : 0,
                  width: video.videoWidth || 0,
                  height: video.videoHeight || 0
                }))
              };
            })();
            """,
            self._handle_probe_result,
        )

    def _handle_media_url(self, media_url: str) -> None:
        if self._finished:
            return
        if looks_like_audio_url(media_url):
            self._audio_url = media_url
            self._finish_when_complete()
            return
        if looks_like_media_url(media_url):
            self._video_candidates.add(media_url)
            self._video_url = max(self._video_candidates, key=media_url_quality_score)
            self._page_url = self._page.url().toString().strip() if self._page is not None else self._url
            self._title = self._page.title().strip() if self._page is not None else ""
            self._source = "network"
            self._finish_when_complete()

    def _handle_probe_result(self, payload) -> None:
        if self._finished or not isinstance(payload, dict):
            return

        page_url = str(payload.get("pageUrl") or "").strip()
        title = str(payload.get("title") or "").strip()
        for resource_url in payload.get("resources") or []:
            resource_url = str(resource_url or "").strip()
            if looks_like_audio_url(resource_url):
                self._audio_url = resource_url
            elif looks_like_media_url(resource_url):
                self._video_candidates.add(resource_url)
        videos = payload.get("videos") or []
        if not isinstance(videos, list):
            return

        for video in videos:
            if not isinstance(video, dict):
                continue
            media_url = str(video.get("mediaUrl") or "").strip()
            if not looks_like_media_url(media_url):
                continue
            self._video_candidates.add(media_url)

        if self._video_candidates:
            self._video_url = max(self._video_candidates, key=media_url_quality_score)
            self._source = "dom"
        if page_url:
            self._page_url = page_url
        if title:
            self._title = title
        self._finish_when_complete()

    def _finish_when_complete(self) -> None:
        if not self._video_url:
            return
        # Give the player time to expose its full-play and adaptive variants before
        # selecting a URL. The first requested stream is often a low-bitrate preview.
        if not self._settle_timer.isActive():
            self._settle_timer.start(2200)

    def _finish_collected_streams(self) -> None:
        if self._finished or not self._video_url:
            return
        self._finish_success(
            DouyinBrowserProbeResult(
                page_url=self._page_url or self._url,
                media_url=self._video_url,
                audio_url=self._audio_url,
                title=self._title,
                source=self._source,
            )
        )

    def _on_timeout(self) -> None:
        self._finish_failed("Timed out while waiting for the browser to expose a Douyin media URL.")

    def _finish_success(self, result: DouyinBrowserProbeResult) -> None:
        self.result = result
        self._finish()

    def _finish_failed(self, message: str) -> None:
        self.error = message
        self._finish()

    def _finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        self._poll_timer.stop()
        self._timeout_timer.stop()
        self._settle_timer.stop()
        self._cleanup()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _cleanup(self) -> None:
        if self._page is not None:
            try:
                self._page.loadFinished.disconnect(self._on_load_finished)
            except Exception:
                pass
            self._page.deleteLater()
            self._page = None

        if self._profile is not None:
            try:
                self._profile.setUrlRequestInterceptor(None)
            except Exception:
                pass
        if self._interceptor is not None:
            self._interceptor.deleteLater()
            self._interceptor = None


def looks_like_media_url(url: str) -> bool:
    lowered_url = (url or "").strip().lower()
    if not lowered_url.startswith(("http://", "https://")):
        return False
    if "douyin.com/video/" in lowered_url or "iesdouyin.com/share/video/" in lowered_url:
        return False
    if "douyinstatic.com" in lowered_url or "/obj/douyin-pc-web/" in lowered_url:
        return False
    if looks_like_audio_url(lowered_url):
        return False
    if "douyinvod.com" in lowered_url:
        return True
    parts = urlsplit(lowered_url)
    query = parse_qs(parts.query)
    if "/aweme/v1/play/" in parts.path and (
        query.get("is_play_url") == ["1"] or bool(query.get("video_id"))
    ):
        return True
    if "mime_type=video" in lowered_url or "video_mp4" in lowered_url or "__vid=" in lowered_url:
        return True
    return False


def media_url_quality_score(url: str) -> float:
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    try:
        bitrate = float((query.get("br") or query.get("bt") or [0])[0])
    except (TypeError, ValueError):
        bitrate = 0.0
    score = bitrate
    if query.get("is_play_url") == ["1"]:
        score += 1000
    if query.get("target"):
        score += 1000
    if query.get("downgrade_264") == ["1"]:
        score += 250
    return score


def looks_like_audio_url(url: str) -> bool:
    lowered_url = (url or "").strip().lower()
    if not lowered_url.startswith(("http://", "https://")):
        return False
    if "douyinvod.com" not in lowered_url:
        return False
    return any(token in lowered_url for token in ("mime_type=audio", "audio_mp4", "media-audio", "/audio/"))


def looks_like_stream_url(url: str) -> bool:
    return looks_like_media_url(url) or looks_like_audio_url(url)


def probe_douyin_video_url(url: str, *, timeout_ms: int = 60000) -> DouyinBrowserProbeResult:
    if QApplication.instance() is None:
        QApplication(["douyin-browser-probe"])
    probe = _DouyinBrowserProbe(url, timeout_ms=timeout_ms)
    QTimer.singleShot(0, probe.start)
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("Failed to create Qt application for browser probe.")
    app.exec()
    if probe.result is not None:
        return probe.result
    raise RuntimeError(probe.error or "Browser probe did not return a media URL.")


def probe_cli(url: str, output_path: str | None = None) -> int:
    try:
        result = probe_douyin_video_url(url)
        payload = {"ok": True, **asdict(result)}
        exit_code = 0
    except Exception as exc:
        payload = {"ok": False, "error": str(exc)}
        exit_code = 1

    text = json.dumps(payload, ensure_ascii=False)
    if output_path:
        Path(output_path).write_text(text, encoding="utf-8")
    else:
        print(text)
    return exit_code


if __name__ == "__main__":
    target_url = sys.argv[1] if len(sys.argv) >= 2 else ""
    target_output = sys.argv[2] if len(sys.argv) >= 3 else None
    raise SystemExit(probe_cli(target_url, target_output))
