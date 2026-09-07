from __future__ import annotations

import re
import os
import shutil
from datetime import date
from pathlib import Path


UPLOAD_BATCH_LIMIT = 50
UPLOAD_NAME_PREFIX = "APP-繁花-王俨-改md5-情报台"


def eligible_materials(rows, records, notes, selected_ids, *, require_files=True):
    selected = set(selected_ids)
    result = []
    for row in rows:
        video_id = row.get("video_id", "")
        record = records.get(video_id, {})
        path = Path(record.get("video_path", ""))
        if (
            video_id in selected
            and not row.get("input_error")
            and record.get("download") == "已下载"
            and record.get("status") == "sample_clear"
            and not notes.get(video_id, {}).get("blocked")
            and (not require_files or path.is_file())
        ):
            result.append({**row, "record": record})
    return result


def suggested_drama_name(materials):
    names = {
        str(item.get("source", {}).get("剧名", "")).strip()
        for item in materials
        if str(item.get("source", {}).get("剧名", "")).strip()
    }
    return names.pop() if len(names) == 1 else ""


def safe_filename_part(value):
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(value).strip())
    cleaned = re.sub(r"\s+", " ", cleaned).rstrip(". ")
    return cleaned


def build_upload_plan(
    materials,
    *,
    drama_name,
    drama_platform_id,
    director,
    uploader_initials,
    upload_date=None,
    batch_limit=UPLOAD_BATCH_LIMIT,
):
    drama_name = safe_filename_part(drama_name)
    drama_platform_id = str(drama_platform_id).strip()
    director = str(director).strip()
    uploader_initials = safe_filename_part(uploader_initials)
    if not drama_name or not drama_platform_id:
        raise ValueError("请选择建议短剧并保存平台短剧 ID")
    if not director:
        raise ValueError("请选择编导")
    if not uploader_initials:
        raise ValueError("请填写上传人缩写")
    if not 1 <= batch_limit <= UPLOAD_BATCH_LIMIT:
        raise ValueError("单批上传数量必须在 1 到 50 之间")

    upload_date = upload_date or date.today()
    items = []
    for sequence, material in enumerate(materials, 1):
        original = Path(material.get("record", {}).get("video_path", ""))
        suffix = original.suffix.lower() or ".mp4"
        name = f"{UPLOAD_NAME_PREFIX}-{drama_name}-{uploader_initials}-{upload_date:%y%m%d}-{sequence:02d}{suffix}"
        items.append({
            "video_id": material.get("video_id", ""),
            "original_path": str(original),
            "upload_name": name,
            "drama_name": drama_name,
            "drama_platform_id": drama_platform_id,
            "director": director,
        })

    return [
        {"index": index // batch_limit + 1, "items": items[index:index + batch_limit]}
        for index in range(0, len(items), batch_limit)
    ]


def stage_upload_batch(batch, staging_root):
    target_folder = Path(staging_root) / f"batch-{int(batch['index']):02d}"
    target_folder.mkdir(parents=True, exist_ok=True)
    staged_items = []
    for item in batch.get("items", []):
        source = Path(item["original_path"])
        if not source.is_file():
            raise FileNotFoundError(f"待上传视频不存在：{source}")
        target = target_folder / item["upload_name"]
        if target.exists():
            if target.stat().st_size != source.stat().st_size:
                raise FileExistsError(f"上传暂存文件已存在且内容不一致：{target}")
        else:
            try:
                os.link(source, target)
            except OSError:
                shutil.copy2(source, target)
        staged_items.append({**item, "upload_path": str(target)})
    return {**batch, "items": staged_items, "folder": str(target_folder)}
