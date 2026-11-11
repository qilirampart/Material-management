"""Local, non-destructive material processing; optional future clip-selection boundary."""
from __future__ import annotations

import hashlib
import math
import os
import subprocess
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from src.batch import save_json
from src.media import (
    FFmpegCancelled, FFmpegError, MAXIMUM_UPLOAD_FILE_SIZE_BYTES,
    probe, run, transcode_for_upload_bitrate, validate_video,
)
from src.upload import safe_filename_part


class ClipSelectionProvider(Protocol):
    """Future model adapter: return ordered source-time ranges, never edit files.

    The caller must validate ranges and obtain human approval before rendering.
    No network request or model client is configured by this module.
    """
    def select_clips(self, video_path: str, metadata: dict, instruction: str) -> list[dict]: ...


def validate_clip_ranges(ranges, duration):
    if not ranges:
        raise ValueError('至少需要一个时间段')
    previous_end = 0.0
    for segment in ranges:
        start, end = float(segment['start']), float(segment['end'])
        if not (math.isfinite(start) and math.isfinite(end) and previous_end <= start < end <= duration):
            raise ValueError('时间段必须有序、不重叠，并在原视频时长内')
        previous_end = end
    return ranges


@dataclass(frozen=True)
class VariantOptions:
    mode: str = 'micro'
    variants: int = 1
    uploader: str = ''
    background: str = 'blur'
    trim_start: float = 0.15
    trim_end: float = 0.15
    speed: float = 1.02
    color_adjust: bool = True
    title: str = ''

    def validate(self):
        if self.mode not in {'micro', 'md5'} or self.background not in {'blur', 'black'}:
            raise ValueError('不支持的处理方式或背景')
        if not 1 <= self.variants <= 10:
            raise ValueError('每条生成数量须为 1–10')
        if not all(math.isfinite(v) for v in (self.trim_start, self.trim_end, self.speed)):
            raise ValueError('时间和速度必须是有效数字')
        if self.trim_start < 0 or self.trim_end < 0 or not 0.8 <= self.speed <= 1.2:
            raise ValueError('裁剪秒数不能为负；速度须为 0.8–1.2 倍')
        if len(self.title) > 40 or '\n' in self.title or '\r' in self.title:
            raise ValueError('标题限一行、40 字以内')
        if self.mode == 'micro' and self.variants > 1 and not self.color_adjust:
            raise ValueError('生成多个微创新版本需启用轻度调色，以区分版本')
        return self


def file_md5(path, should_stop=None):
    digest = hashlib.md5()
    with Path(path).open('rb') as stream:
        while True:
            if should_stop and should_stop():
                raise FFmpegCancelled('已停止素材再加工')
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _filter_path(path):
    return str(Path(path).resolve()).replace('\\', '/').replace(':', '\\:').replace("'", "'\\''")


def _title_filter(text_path):
    candidates = [
        Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc',
        Path('/System/Library/Fonts/PingFang.ttc'),
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
    ]
    font = next((p for p in candidates if p.is_file()), None)
    if font is None:
        raise ValueError('未找到标题字体，请先关闭标题选项')
    return (f"drawtext=fontfile='{_filter_path(font)}':textfile='{_filter_path(text_path)}':"
            "expansion=none:fontsize=28:fontcolor=white:box=1:boxcolor=black@0.6:"
            "boxborderw=12:x=(w-text_w)/2:y=32")


def build_video_filter(options, version=1, text_path=None):
    # Fit the entire foreground within a 648x1080 safe area; never crop subtitles.
    time_filter = f'setpts=(PTS-STARTPTS)/{options.speed}'
    if options.background == 'blur':
        graph = (f'[0:v]{time_filter},split=2[bg][fg];'
                 '[bg]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,'
                 'boxblur=20:2[back];'
                 '[fg]scale=648:1080:force_original_aspect_ratio=decrease:force_divisible_by=2[front];'
                 '[back][front]overlay=(W-w)/2:(H-h)/2:shortest=1,setsar=1')
    else:
        graph = (f'[0:v]{time_filter},scale=648:1080:force_original_aspect_ratio=decrease:'
                 'force_divisible_by=2,pad=720:1280:(ow-iw)/2:(oh-ih)/2:black,setsar=1')
    if options.color_adjust:
        graph += f',eq=brightness={0.002 * version:.3f}:contrast={1 + 0.003 * version:.3f}:saturation=1.015'
    if options.title and text_path:
        graph += ',' + _title_filter(text_path).replace('fontsize=28', f'fontsize={min(28, 640 // max(1, len(options.title)))}')
    return graph + ',format=yuv420p[outv]'


def generate_variants(items, output_root, options, *, progress=None, should_stop=None):
    options.validate()
    run_id = datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6]
    root = Path(output_root) / run_id
    root.mkdir(parents=True, exist_ok=False)
    result = {'outputs': [], 'failed': [], 'stopped': False, 'manifest': str(root / 'manifest.json')}
    total = len(items) * options.variants
    index = 0

    def persist():
        save_json(Path(result['manifest']), {'options': asdict(options), **result})

    persist()
    for item in items:
        source_metadata = None
        source_md5 = None
        for version in range(1, options.variants + 1):
            if should_stop and should_stop():
                result['stopped'] = True
                persist()
                return result
            index += 1
            target = None
            if progress:
                progress({'phase': 'started', 'index': index, 'total': total, 'video_id': item['video_id']})
            try:
                source = Path(item['path']).resolve()
                if source_metadata is None:
                    source_metadata = probe(source)
                    source_md5 = file_md5(source, should_stop)
                mode_name = '改md5' if options.mode == 'md5' else '微创新'
                drama = safe_filename_part(item.get('drama') or '未命名剧集') or '未命名剧集'
                uploader = safe_filename_part(options.uploader) or '未填'
                target_dir = root / drama / mode_name
                target_dir.mkdir(parents=True, exist_ok=True)
                target = target_dir / f'APP-繁花-王俨-{mode_name}-{drama}-{uploader}-{datetime.now():%y%m%d}-{index:03d}.mp4'
                if options.mode == 'md5':
                    run(['ffmpeg', '-y', '-v', 'error', '-i', str(source), '-map', '0:v:0',
                         '-map', '0:a?', '-c', 'copy', '-metadata', f'comment=variant-{uuid.uuid4().hex}',
                         '-movflags', '+faststart', str(target)],
                        timeout=max(600, int(source_metadata['duration'] * 2)), should_stop=should_stop)
                    metadata = validate_video(target, should_stop=should_stop)
                    if metadata['file_size_bytes'] > MAXIMUM_UPLOAD_FILE_SIZE_BYTES:
                        raise ValueError('文件超过平台 510 MB 上限；仅改 MD5 不会缩小文件，请先剪辑或压缩')
                else:
                    clip_duration = source_metadata['duration'] - options.trim_start - options.trim_end
                    if clip_duration < 0.5:
                        raise ValueError('去头尾后不足 0.5 秒，请减少裁剪时长')
                    with tempfile.TemporaryDirectory(prefix='dz-variant-') as work:
                        text_path = Path(work) / 'title.txt'
                        text_path.write_text(options.title, encoding='utf-8')
                        metadata = transcode_for_upload_bitrate(
                            source, target, video_filter=build_video_filter(options, version, text_path),
                            audio_filter=f'asetpts=PTS-STARTPTS,atempo={options.speed}',
                            clip_start=options.trim_start, clip_duration=clip_duration,
                            output_duration=clip_duration / options.speed, should_stop=should_stop,
                            progress=(lambda phase: progress({'phase': phase, 'index': index, 'total': total,
                                                             'video_id': item['video_id']})) if progress else None,
                        )
                output_md5 = file_md5(target, should_stop)
                if output_md5 == source_md5:
                    raise ValueError('输出与原文件 MD5 相同，请检查处理参数')
                result['outputs'].append({
                    'path': str(target.resolve()), 'metadata': metadata, 'drama': drama,
                    'source_path': str(source), 'source_video_id': item['video_id'],
                    'source_md5': source_md5, 'output_md5': output_md5,
                    'mode': options.mode, 'version': version, 'options': asdict(options),
                    'upload_drama_info': item.get('upload_drama_info', {}),
                })
                if progress:
                    progress({'phase': 'completed', 'index': index, 'total': total, 'video_id': item['video_id']})
            except FFmpegCancelled:
                if target:
                    target.unlink(missing_ok=True)
                result['stopped'] = True
                persist()
                return result
            except (OSError, ValueError, FFmpegError, subprocess.SubprocessError) as exc:
                if target:
                    target.unlink(missing_ok=True)
                message = str(exc) if isinstance(exc, ValueError) else ('本地视频处理失败：' + str(exc)[-600:])
                result['failed'].append({'video_id': item['video_id'], 'version': version, 'error': message})
                if progress:
                    progress({'phase': 'failed', 'index': index, 'total': total,
                              'video_id': item['video_id'], 'error': message})
            persist()
    return result
