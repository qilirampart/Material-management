"""Capacity policy for at most two independent MD5 inputs."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import ctypes
import os
from pathlib import Path

from src.disk_budget import DiskSpaceLow, estimate_output_bytes, require_disk_space


def available_memory():
    try:
        if os.name=='nt':
            class Status(ctypes.Structure):
                _fields_=[('length',ctypes.c_uint32),('load',ctypes.c_uint32),
                          ('memory',ctypes.c_uint64*7)]
            status=Status()
            status.length=ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return status.memory[1]
        else:
            return os.sysconf('SC_AVPHYS_PAGES')*os.sysconf('SC_PAGE_SIZE')
    except (OSError, ValueError, AttributeError):
        pass
    return None


def resource_issue(folder_bytes, lanes=2, *, downloading=False):
    if lanes==2 or downloading:
        if (os.cpu_count() or 0)<4:
            return '本机可用逻辑核心少于 4 个'
        memory=available_memory()
        if memory is None:
            return '无法确认本机可用内存'
        if memory < 2*1024**3:
            return '当前可用内存不足 2 GiB'
    for folder, amount in folder_bytes.items():
        try:
            require_disk_space(folder,amount*lanes+(256*1024**2 if downloading else 0))
        except DiskSpaceLow:
            return '素材盘空间不足'
        except OSError:
            return '无法读取素材盘的可用空间'
    return ''


def per_input_budget(items,options):
    sizes={}
    for item in items:
        folder=Path(item['batch_folder'])
        try:
            amount=estimate_output_bytes({'file_size_bytes':Path(item['path']).stat().st_size},options)*options.variants
        except (OSError, TypeError, ValueError):
            continue  # existing processing reports missing/invalid input individually
        sizes[folder]=max(sizes.get(folder,0),amount)
    return sizes


def choose_lanes(requested, downloading, supported):
    if requested<2:
        return 1,''
    if not supported:
        return 1,'unsupported'
    return 2,'download' if downloading else ''


def limited_work(items, work, available_slots, should_stop):
    pending=iter(items)
    active=set()
    exhausted=False
    with ThreadPoolExecutor(max_workers=2) as pool:
        while not exhausted or active:
            if should_stop():
                exhausted=True
            while not exhausted and len(active)<available_slots() and not should_stop():
                try:
                    item=next(pending)
                except StopIteration:
                    exhausted=True
                else:
                    active.add(pool.submit(work,item))
            if active:
                finished,active=wait(active,timeout=.15,return_when=FIRST_COMPLETED)
                for job in finished:
                    yield job.result()
