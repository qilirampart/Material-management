"""Conservative output estimates; never remove media to make room."""
import shutil
from pathlib import Path
from src.media import MAXIMUM_UPLOAD_FILE_SIZE_BYTES, TARGET_UPLOAD_BITRATE_KBPS, UPLOAD_AUDIO_RESERVE_KBPS

DISK_RESERVE_BYTES = 256 * 1024 * 1024


class DiskSpaceLow(ValueError):
    pass


def estimate_output_bytes(metadata, options):
    if options.mode == 'md5':
        return int(metadata.get('file_size_bytes', 0) * 1.01) + 1024 * 1024
    speed = options.speed
    if options.randomize and 'speed' in options.random_ranges:
        speed = min(options.random_ranges['speed'])
    seconds = (options.range_duration if options.clip_mode == 'range' else
               max(0, metadata['duration'] - options.trim_start - options.trim_end)) / speed
    seconds += (options.intro_duration if options.intro_path else 0) + (options.outro_duration if options.outro_path else 0)
    amount = int(seconds * (TARGET_UPLOAD_BITRATE_KBPS + UPLOAD_AUDIO_RESERVE_KBPS) * 1000 / 8 * 1.05)
    return min(MAXIMUM_UPLOAD_FILE_SIZE_BYTES, amount) + 1024 * 1024


def require_disk_space(path, estimated_bytes):
    target = Path(path).resolve()
    while not target.exists():
        if target.parent == target:
            raise OSError('输出磁盘当前不可用')
        target = target.parent
    free = shutil.disk_usage(target).free
    if free < estimated_bytes + DISK_RESERVE_BYTES:
        raise DiskSpaceLow(f'磁盘空间不足：可用 {free / 1048576:.0f} MB，预计新增 '
                           f'{estimated_bytes / 1048576:.0f} MB，另需保留 256 MB；已停止剩余处理，已完成文件保留。')
