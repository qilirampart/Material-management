from __future__ import annotations

import json
import os
import subprocess
import time
from functools import lru_cache
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


MINIMUM_VIDEO_BITRATE_KBPS = 3500
TARGET_UPLOAD_BITRATE_KBPS = 4200


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _frame_rate(value):
    if not value or value == "0/0":
        return 0.0
    numerator, separator, denominator = str(value).partition("/")
    if not separator:
        return _number(value)
    denominator_value = _number(denominator)
    return _number(numerator) / denominator_value if denominator_value else 0.0


def describe_video(metadata):
    if not isinstance(metadata, dict) or not metadata:
        return ""
    parts = []
    width, height = metadata.get("width"), metadata.get("height")
    if width and height:
        parts.append(f"{width}×{height}")
    frame_rate = _number(metadata.get("frame_rate"))
    if frame_rate:
        parts.append(f"{frame_rate:g}fps")
    bitrate = _number(metadata.get("total_bitrate_bps"))
    if bitrate:
        parts.append(f"{bitrate / 1_000_000:.2f} Mbps")
    codec = str(metadata.get("video_codec") or "").strip()
    if codec:
        parts.append(codec.upper())
    size = _number(metadata.get("file_size_bytes"))
    if size:
        parts.append(f"{size / 1048576:.1f} MB")
    return " · ".join(parts)


def describe_bitrate(metadata, minimum_kbps=MINIMUM_VIDEO_BITRATE_KBPS):
    if not isinstance(metadata, dict) or not metadata:
        return "待检测"
    video_bitrate = _number(metadata.get("video_bitrate_bps"))
    total_bitrate = _number(metadata.get("total_bitrate_bps"))
    bitrate = video_bitrate or total_bitrate
    if bitrate <= 0:
        return "未读取到码率"
    kbps = bitrate / 1000
    source = "视频" if video_bitrate else "总"
    result = "达标" if kbps > minimum_kbps else f"不足 {minimum_kbps}"
    return f"{source} {kbps:,.0f} kbps · {result}"


def effective_video_bitrate_bps(metadata):
    if not isinstance(metadata, dict):
        return 0
    return int(_number(metadata.get("video_bitrate_bps")) or _number(metadata.get("total_bitrate_bps")))


def run(command, timeout=180):
    result = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace",
                            timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode:
        raise FFmpegError(result.stderr[-1000:])
    return result.stdout


def preferred_hardware_h264_encoder(encoders_output: str) -> str | None:
    available = str(encoders_output or "")
    for encoder in ("h264_nvenc", "h264_qsv", "h264_amf"):
        if encoder in available:
            return encoder
    return None


@lru_cache(maxsize=1)
def hardware_h264_encoder() -> str | None:
    try:
        return preferred_hardware_h264_encoder(
            run(["ffmpeg", "-hide_banner", "-encoders"], timeout=20)
        )
    except FFmpegError:
        return None


def probe(path):
    path = Path(path)
    info = json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]))
    streams = info.get("streams", [])
    videos = [s for s in streams if s.get("codec_type") == "video"]
    if not videos:
        raise FFmpegError("文件没有视频流")
    duration = float(info.get("format", {}).get("duration", 0))
    if duration <= 0:
        raise FFmpegError("无有效视频时长")
    video = videos[0]
    file_size = int(_number(info.get("format", {}).get("size"), path.stat().st_size))
    total_bitrate = int(_number(info.get("format", {}).get("bit_rate")))
    if total_bitrate <= 0 and duration > 0:
        total_bitrate = round(file_size * 8 / duration)
    return {
        "duration": duration,
        "audio": any(s.get("codec_type") == "audio" for s in streams),
        "width": video["width"],
        "height": video["height"],
        "file_size_bytes": file_size,
        "total_bitrate_bps": total_bitrate,
        "video_bitrate_bps": int(_number(video.get("bit_rate"))),
        "frame_rate": _frame_rate(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        "video_codec": str(video.get("codec_name") or ""),
    }


def ensure_video_has_decodable_frame(path):
    probe(path)
    run(["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-frames:v", "1", "-f", "null", "-"])


def validate_video(path):
    metadata = probe(path)
    # Decode all streams once before treating a completed download as reusable.
    run(["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"], timeout=600)
    return metadata


def transcode_for_upload_bitrate(
    source_path,
    output_path,
    *,
    target_kbps=TARGET_UPLOAD_BITRATE_KBPS,
    minimum_kbps=MINIMUM_VIDEO_BITRATE_KBPS,
    progress=None,
):
    source_path = Path(source_path)
    output_path = Path(output_path)
    source_metadata = probe(source_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    timeout = max(600, round(source_metadata["duration"] * 6))
    def command_for(encoder):
        command = [
            "ffmpeg", "-y", "-v", "error", "-i", str(source_path),
            "-map", "0:v:0", "-map", "0:a?",
            "-c:v", encoder,
        ]
        if encoder == "libx264":
            command += ["-preset", "veryfast", "-pix_fmt", "yuv420p"]
        elif encoder == "h264_nvenc":
            command += ["-preset", "p4", "-rc", "cbr", "-pix_fmt", "yuv420p"]
        elif encoder == "h264_amf":
            command += ["-rc", "cbr", "-pix_fmt", "yuv420p"]
        else:  # h264_qsv
            command += ["-preset", "fast", "-pix_fmt", "nv12"]
        command += [
            "-b:v", f"{target_kbps}k",
            "-minrate", f"{target_kbps}k",
            "-maxrate", f"{target_kbps}k",
            "-bufsize", f"{target_kbps * 2}k",
        ]
        if encoder == "libx264":
            command += ["-x264-params", "nal-hrd=cbr:filler=1"]
        return command + ["-c:a", "copy", "-movflags", "+faststart", str(output_path)]

    started_at = time.monotonic()
    encoder = hardware_h264_encoder() or "libx264"
    hardware_accelerated = encoder != "libx264"
    try:
        if progress:
            progress('encoding')
        encoding_started_at = time.monotonic()
        try:
            run(command_for(encoder), timeout=timeout)
        except FFmpegError:
            if not hardware_accelerated:
                raise
            output_path.unlink(missing_ok=True)
            encoder = "libx264"
            hardware_accelerated = False
            run(command_for(encoder), timeout=timeout)
        encoding_seconds = time.monotonic() - encoding_started_at
        if progress:
            progress('validating')
        validating_started_at = time.monotonic()
        metadata = dict(validate_video(output_path))
        metadata["transcode"] = {
            "video_encoder": encoder,
            "hardware_accelerated": hardware_accelerated,
            "encoding_seconds": round(encoding_seconds, 3),
            "validation_seconds": round(time.monotonic() - validating_started_at, 3),
            "total_seconds": round(time.monotonic() - started_at, 3),
        }
        if effective_video_bitrate_bps(metadata) <= minimum_kbps * 1000:
            raise FFmpegError(
                f"转码后视频码率仍未超过 {minimum_kbps} kbps："
                f"{effective_video_bitrate_bps(metadata) / 1000:.0f} kbps"
            )
        return metadata
    except Exception:
        output_path.unlink(missing_ok=True)
        raise


def merge_av_streams(video_path, audio_path, output_path):
    run(["ffmpeg", "-y", "-v", "error", "-i", str(video_path), "-i", str(audio_path),
         "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", str(output_path)])


def extract_frames(path, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    meta = probe(path)
    end = min(3.0, meta["duration"])
    targets = [0.0, 1.0, 2.0] if end >= 3 else [0.0, end / 3, end * 2 / 3]
    frames = []
    # Select decoded frames by timestamps, avoiding keyframe seeking and reporting actual PTS.
    for index, target in enumerate(targets, 1):
        output = folder / f"frame_{index}.png"
        output.unlink(missing_ok=True)
        command = ["ffmpeg", "-y", "-v", "info", "-i", str(path), "-vf",
                   f"setpts=PTS-STARTPTS,select=gte(t\\,{target:.9f}),showinfo", "-frames:v", "1", str(output)]
        result = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace", timeout=120,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        import re
        match = re.search(r"\bn:\s*0\s+pts:.*?pts_time:([\d.eE+-]+)", result.stderr)
        if result.returncode or not output.is_file() or not match:
            raise FFmpegError(f"第{index}帧抽取失败")
        seconds = float(match.group(1))
        if frames and seconds <= frames[-1]["seconds"]:
            raise FFmpegError("视频无法提供三张独立帧")
        frames.append({"path": str(output.resolve()), "seconds": seconds, "requested_seconds": target})
    return frames
