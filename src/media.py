from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


def run(command, timeout=180):
    result = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace",
                            timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode:
        raise FFmpegError(result.stderr[-1000:])
    return result.stdout


def probe(path):
    info = json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]))
    streams = info.get("streams", [])
    videos = [s for s in streams if s.get("codec_type") == "video"]
    if not videos:
        raise FFmpegError("文件没有视频流")
    duration = float(info.get("format", {}).get("duration", 0))
    if duration <= 0:
        raise FFmpegError("无有效视频时长")
    return {"duration": duration, "audio": any(s.get("codec_type") == "audio" for s in streams),
            "width": videos[0]["width"], "height": videos[0]["height"]}


def ensure_video_has_decodable_frame(path):
    probe(path)
    run(["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-frames:v", "1", "-f", "null", "-"])


def validate_video(path):
    metadata = probe(path)
    # Decode all streams once before treating a completed download as reusable.
    run(["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"], timeout=600)
    return metadata


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
