from __future__ import annotations

import re
import os
import shutil
import json
import filecmp
import time
import uuid
from datetime import date
from pathlib import Path

from src.media import (
    MINIMUM_VIDEO_BITRATE_KBPS,
    effective_video_bitrate_bps,
    transcode_for_upload_bitrate,
)


UPLOAD_BATCH_LIMIT = 50
UPLOAD_NAME_PREFIX = "APP-繁花-王俨-改md5-情报台"
FIXED_DEPARTMENTS = [
    "IAP投放组", "代理组", "免费IAA投放部", "免费投放三组", "免费投放二组", "免费投放四组",
    "免费投放组", "厂商-代理", "合肥免费投放组", "客户端一组", "客户端二组", "小说投放一部",
    "广州-自投", "广州自投二组", "广点通投放组-广州", "快应用一组", "快应用三组", "快应用二组",
    "新媒体-自投", "新媒体-自投二组", "杭州小说投放三组", "杭州小说投放二组",
    "杭州小说投放四组", "杭州投放组", "杭州漫剧投放部", "杭州短剧投放一组", "河马代理组",
    "深圳免费投放组", "深圳小说投放部", "深圳投放组", "百度投放组", "自动化投放组",
    "自投四组", "设计部-短剧", "重庆-自投",
]


def _replace_staged_file(temporary: Path, target: Path) -> None:
    """Replace a staged file, tolerating Windows' short-lived sharing locks."""
    for attempt in range(5):
        try:
            os.replace(temporary, target)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.025 * (attempt + 1))


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
        record = material.get("record", {})
        enhanced = Path(record.get("bitrate_enhanced_path", ""))
        enhanced_metadata = record.get("bitrate_enhanced_metadata", {})
        use_enhanced = (
            enhanced.is_file()
            and effective_video_bitrate_bps(enhanced_metadata) > MINIMUM_VIDEO_BITRATE_KBPS * 1000
        )
        original = enhanced if use_enhanced else Path(record.get("video_path", ""))
        suffix = original.suffix.lower() or ".mp4"
        name = f"{UPLOAD_NAME_PREFIX}-{drama_name}-{uploader_initials}-{upload_date:%y%m%d}-{sequence:02d}{suffix}"
        items.append({
            "video_id": material.get("video_id", ""),
            "original_path": str(original),
            "upload_name": name,
            "drama_name": drama_name,
            "drama_platform_id": drama_platform_id,
            "director": director,
            "metadata": enhanced_metadata if use_enhanced else record.get("metadata", {}),
            "uses_bitrate_enhanced_copy": use_enhanced,
        })

    return [
        {"index": index // batch_limit + 1, "items": items[index:index + batch_limit]}
        for index in range(0, len(items), batch_limit)
    ]


def stage_upload_batch(batch, staging_root, *, normalize_bitrate=False):
    target_folder = Path(staging_root) / f"batch-{int(batch['index']):02d}"
    target_folder.mkdir(parents=True, exist_ok=True)
    staged_items = []
    for item in batch.get("items", []):
        source = Path(item["original_path"])
        if not source.is_file():
            raise FileNotFoundError(f"待上传视频不存在：{source}")
        target = target_folder / item["upload_name"]
        source_metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        source_bitrate = effective_video_bitrate_bps(source_metadata)
        needs_bitrate_normalization = (
            normalize_bitrate
            and source_bitrate > 0
            and source_bitrate <= MINIMUM_VIDEO_BITRATE_KBPS * 1000
        )
        if target.exists():
            if not target.is_file():
                raise FileExistsError(f"上传暂存位置被目录占用：{target}")
            if not needs_bitrate_normalization and filecmp.cmp(source, target, shallow=False):
                staged_items.append({
                    **item,
                    "upload_path": str(target),
                    "bitrate_normalized": False,
                    "upload_metadata": source_metadata,
                })
                continue

        temporary = target.with_name(
            f".{target.stem}.{uuid.uuid4().hex}.tmp{target.suffix or '.mp4'}"
        )
        try:
            if needs_bitrate_normalization:
                upload_metadata = transcode_for_upload_bitrate(source, temporary)
            else:
                try:
                    os.link(source, temporary)
                except OSError:
                    shutil.copy2(source, temporary)
                upload_metadata = source_metadata
            _replace_staged_file(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        staged_items.append({
            **item,
            "upload_path": str(target),
            "bitrate_normalized": needs_bitrate_normalization,
            "upload_metadata": upload_metadata,
        })
    return {**batch, "items": staged_items, "folder": str(target_folder)}


def enhance_selected_bitrates(
    records,
    video_ids,
    output_folder,
    item_completed=None,
    item_failed=None,
    item_started=None,
    item_phase=None,
    should_stop=None,
):
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)
    enhanced = {}
    total = len(video_ids)
    for index, video_id in enumerate(video_ids, 1):
        if should_stop and should_stop():
            break
        if item_started:
            item_started(video_id, index, total)
        record = records.get(video_id, {})
        existing = Path(record.get("bitrate_enhanced_path", ""))
        existing_metadata = record.get("bitrate_enhanced_metadata", {})
        if (
            existing.is_file()
            and effective_video_bitrate_bps(existing_metadata) > MINIMUM_VIDEO_BITRATE_KBPS * 1000
        ):
            values = {
                "bitrate_enhanced_path": str(existing.resolve()),
                "bitrate_enhanced_metadata": existing_metadata,
            }
            enhanced[video_id] = values
            if item_completed:
                item_completed(video_id, values)
            continue
        source = Path(record.get("video_path", ""))
        source_bitrate = effective_video_bitrate_bps(record.get("metadata"))
        if (
            not source.is_file()
            or source_bitrate <= 0
            or source_bitrate > MINIMUM_VIDEO_BITRATE_KBPS * 1000
        ):
            continue
        target = output_folder / f"{safe_filename_part(video_id)}.mp4"
        try:
            if item_phase:
                metadata = transcode_for_upload_bitrate(
                    source,
                    target,
                    progress=lambda phase: item_phase(video_id, phase),
                )
            else:
                metadata = transcode_for_upload_bitrate(source, target)
        except Exception as exc:
            if item_failed:
                item_failed(video_id, exc)
            continue
        values = {
            "bitrate_enhanced_path": str(target.resolve()),
            "bitrate_enhanced_metadata": metadata,
        }
        enhanced[video_id] = values
        if item_completed:
            item_completed(video_id, values)
    return enhanced


def load_upload_preferences(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        data = {}
    stored_dramas = data.get("dramas") if isinstance(data.get("dramas"), dict) else {}
    dramas = {}
    for name, stored in stored_dramas.items():
        if not isinstance(stored, dict):
            continue
        ids = stored.get("ids") if isinstance(stored.get("ids"), dict) else {}
        ids = {
            str(platform_id): {"director": str(details.get("director", "")).strip()}
            for platform_id, details in ids.items()
            if str(platform_id).strip() and isinstance(details, dict)
        }
        legacy_id = str(stored.get("platform_id", "")).strip()
        if legacy_id:
            ids.setdefault(legacy_id, {"director": str(stored.get("director", "")).strip()})
        last_id = str(stored.get("last_id", legacy_id)).strip()
        dramas[str(name)] = {"ids": ids, "last_id": last_id if last_id in ids else next(iter(ids), "")}
    return {
        "dramas": dramas,
        "uploader_initials": str(data.get("uploader_initials", "")).strip(),
    }


def upload_preference_entries(preferences):
    entries = []
    for drama_name, drama in preferences.get("dramas", {}).items():
        for platform_id, details in drama.get("ids", {}).items():
            entries.append({
                "drama_name": str(drama_name),
                "drama_platform_id": str(platform_id),
                "director": str(details.get("director", "")).strip(),
            })
    return sorted(entries, key=lambda item: (item["drama_name"], item["drama_platform_id"]))


def _write_upload_preferences(path, preferences):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(preferences, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def remember_upload_preferences(path, *, drama_name, drama_platform_id, director, uploader_initials):
    preferences = load_upload_preferences(path)
    name = str(drama_name).strip()
    platform_id = str(drama_platform_id).strip()
    drama = preferences["dramas"].setdefault(name, {"ids": {}, "last_id": ""})
    drama["ids"][platform_id] = {"director": str(director).strip()}
    drama["last_id"] = platform_id
    preferences["uploader_initials"] = str(uploader_initials).strip()
    _write_upload_preferences(path, preferences)


def forget_upload_preference(path, drama_name, drama_platform_id):
    preferences = load_upload_preferences(path)
    name = str(drama_name).strip()
    platform_id = str(drama_platform_id).strip()
    drama = preferences["dramas"].get(name)
    if not drama or platform_id not in drama.get("ids", {}):
        return False
    del drama["ids"][platform_id]
    if not drama["ids"]:
        del preferences["dramas"][name]
    else:
        drama["last_id"] = next(iter(drama["ids"]))
    _write_upload_preferences(path, preferences)
    return True
