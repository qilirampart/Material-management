import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from unittest.mock import patch

from src.upload import (
    build_upload_plan,
    eligible_materials,
    enhance_selected_bitrates,
    forget_upload_preference,
    load_upload_preferences,
    remember_upload_preferences,
    stage_upload_batch,
    suggested_drama_name,
    upload_preference_entries,
)


class UploadPreparationTests(unittest.TestCase):
    def test_only_selected_downloaded_and_clear_materials_are_eligible(self):
        rows = [
            {"video_id": "1", "input_error": "", "source": {"剧名": "婚房门后的秘密"}},
            {"video_id": "2", "input_error": "", "source": {"剧名": "婚房门后的秘密"}},
            {"video_id": "3", "input_error": "", "source": {"剧名": "婚房门后的秘密"}},
        ]
        records = {
            "1": {"status": "sample_clear", "download": "已下载", "video_path": "one.mp4"},
            "2": {"status": "blocked", "download": "已下载", "video_path": "two.mp4"},
            "3": {"status": "sample_clear", "download": "已下载", "video_path": "three.mp4"},
        }
        notes = {"3": {"blocked": True}}

        result = eligible_materials(rows, records, notes, {"1", "2", "3"}, require_files=False)

        self.assertEqual([item["video_id"] for item in result], ["1"])

    def test_drama_name_is_prefilled_only_when_selected_materials_agree(self):
        same = [
            {"source": {"剧名": "婚房门后的秘密"}},
            {"source": {"剧名": " 婚房门后的秘密 "}},
        ]
        mixed = same + [{"source": {"剧名": "另一部剧"}}]

        self.assertEqual(suggested_drama_name(same), "婚房门后的秘密")
        self.assertEqual(suggested_drama_name(mixed), "")

    def test_plan_splits_at_fifty_and_generates_safe_upload_names(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            materials = []
            for index in range(51):
                path = root / f"source-{index}.mp4"
                path.write_bytes(b"video")
                materials.append({
                    "video_id": str(index),
                    "source": {"剧名": "婚房/门后的秘密"},
                    "record": {"video_path": str(path)},
                })

            batches = build_upload_plan(
                materials,
                drama_name="婚房/门后的秘密",
                drama_platform_id="98765",
                director="王俨",
                uploader_initials="ZYY",
                upload_date=date(2026, 9, 7),
            )

            self.assertEqual([len(batch["items"]) for batch in batches], [50, 1])
            first = batches[0]["items"][0]
            last = batches[1]["items"][0]
            self.assertEqual(first["upload_name"], "APP-繁花-王俨-改md5-情报台-婚房门后的秘密-ZYY-260907-01.mp4")
            self.assertEqual(last["upload_name"], "APP-繁花-王俨-改md5-情报台-婚房门后的秘密-ZYY-260907-51.mp4")
            self.assertEqual(first["drama_platform_id"], "98765")

    def test_plan_requires_dynamic_upload_information(self):
        with self.assertRaisesRegex(ValueError, "建议短剧"):
            build_upload_plan([], drama_name="", drama_platform_id="", director="", uploader_initials="")

    def test_plan_prefers_explicitly_enhanced_video_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            enhanced = root / "enhanced.mp4"
            source.write_bytes(b"source")
            enhanced.write_bytes(b"enhanced")
            enhanced_metadata = {"video_bitrate_bps": 4_200_000}

            batches = build_upload_plan(
                [{
                    "video_id": "123",
                    "record": {
                        "video_path": str(source),
                        "metadata": {"video_bitrate_bps": 1_200_000},
                        "bitrate_enhanced_path": str(enhanced),
                        "bitrate_enhanced_metadata": enhanced_metadata,
                    },
                }],
                drama_name="测试短剧",
                drama_platform_id="456",
                director="测试编导",
                uploader_initials="ZYY",
            )

            item = batches[0]["items"][0]
            self.assertEqual(item["original_path"], str(enhanced))
            self.assertEqual(item["metadata"], enhanced_metadata)
            self.assertTrue(item["uses_bitrate_enhanced_copy"])

    def test_staging_keeps_source_and_creates_named_upload_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "downloaded.mp4"
            source.write_bytes(b"video-content")
            batch = {
                "index": 1,
                "items": [{
                    "video_id": "123",
                    "original_path": str(source),
                    "upload_name": "APP-繁花-王俨-改md5-情报台-测试-ZYY-260907-01.mp4",
                }],
            }

            staged = stage_upload_batch(batch, root / "upload-staging")

            staged_path = Path(staged["items"][0]["upload_path"])
            self.assertTrue(source.is_file())
            self.assertTrue(staged_path.is_file())
            self.assertEqual(staged_path.read_bytes(), b"video-content")
            self.assertEqual(staged_path.name, batch["items"][0]["upload_name"])

    @patch("src.upload.transcode_for_upload_bitrate")
    def test_staging_transcodes_low_bitrate_copy_and_keeps_source(self, transcode):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "downloaded.mp4"
            source.write_bytes(b"original-video")
            batch = {
                "index": 1,
                "items": [{
                    "video_id": "123",
                    "original_path": str(source),
                    "upload_name": "upload.mp4",
                    "metadata": {"video_bitrate_bps": 1_200_000},
                }],
            }
            converted_metadata = {"video_bitrate_bps": 4_200_000}

            def create_upload_copy(source_path, output_path):
                Path(output_path).write_bytes(b"normalized-video")
                return converted_metadata

            transcode.side_effect = create_upload_copy

            staged = stage_upload_batch(
                batch,
                root / "upload-staging",
                normalize_bitrate=True,
            )

            staged_item = staged["items"][0]
            self.assertEqual(source.read_bytes(), b"original-video")
            self.assertEqual(Path(staged_item["upload_path"]).read_bytes(), b"normalized-video")
            self.assertTrue(staged_item["bitrate_normalized"])
            self.assertEqual(staged_item["upload_metadata"], converted_metadata)
            transcode.assert_called_once()

    @patch("src.upload.transcode_for_upload_bitrate")
    def test_explicit_enhancement_creates_reusable_upload_copy(self, transcode):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "downloaded.mp4"
            source.write_bytes(b"original-video")
            metadata = {"video_bitrate_bps": 4_200_000}

            def create_copy(_source, output):
                Path(output).write_bytes(b"enhanced-video")
                return metadata

            transcode.side_effect = create_copy
            records = {
                "123": {
                    "video_path": str(source),
                    "metadata": {"video_bitrate_bps": 1_200_000},
                },
            }

            updates = enhance_selected_bitrates(records, ["123"], root / "enhanced")

            self.assertEqual(source.read_bytes(), b"original-video")
            self.assertEqual(Path(updates["123"]["bitrate_enhanced_path"]).read_bytes(), b"enhanced-video")
            self.assertEqual(updates["123"]["bitrate_enhanced_metadata"], metadata)

    @patch("src.upload.transcode_for_upload_bitrate")
    def test_explicit_enhancement_keeps_other_items_when_one_transcode_fails(self, transcode):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            records = {}
            for video_id in ("1", "2", "3"):
                source = root / f"{video_id}.mp4"
                source.write_bytes(b"original-video")
                records[video_id] = {
                    "video_path": str(source),
                    "metadata": {"video_bitrate_bps": 1_200_000},
                }

            def convert(_source, output):
                if Path(output).stem == "2":
                    raise RuntimeError("broken input")
                Path(output).write_bytes(b"enhanced-video")
                return {"video_bitrate_bps": 4_200_000}

            transcode.side_effect = convert
            completed = []
            failed = []

            updates = enhance_selected_bitrates(
                records,
                ["1", "2", "3"],
                root / "enhanced",
                item_completed=lambda video_id, values: completed.append((video_id, values)),
                item_failed=lambda video_id, error: failed.append((video_id, type(error).__name__)),
            )

            self.assertEqual(set(updates), {"1", "3"})
            self.assertEqual([video_id for video_id, _values in completed], ["1", "3"])
            self.assertEqual(failed, [("2", "RuntimeError")])

    @patch("src.upload.transcode_for_upload_bitrate")
    def test_explicit_enhancement_stops_before_starting_next_item(self, transcode):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            records = {}
            for video_id in ("1", "2"):
                source = root / f"{video_id}.mp4"
                source.write_bytes(b"original-video")
                records[video_id] = {
                    "video_path": str(source),
                    "metadata": {"video_bitrate_bps": 1_200_000},
                }
            stop = {"requested": False}

            def convert(_source, output):
                Path(output).write_bytes(b"enhanced-video")
                stop["requested"] = True
                return {"video_bitrate_bps": 4_200_000}

            transcode.side_effect = convert
            started = []

            updates = enhance_selected_bitrates(
                records,
                ["1", "2"],
                root / "enhanced",
                item_started=lambda video_id, index, total: started.append((video_id, index, total)),
                should_stop=lambda: stop["requested"],
            )

            self.assertEqual(set(updates), {"1"})
            self.assertEqual(started, [("1", 1, 2)])
            self.assertEqual(transcode.call_count, 1)

    @patch("src.upload.transcode_for_upload_bitrate")
    def test_staging_can_leave_low_bitrate_source_unchanged(self, transcode):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "downloaded.mp4"
            source.write_bytes(b"original-video")
            batch = {
                "index": 1,
                "items": [{
                    "original_path": str(source),
                    "upload_name": "upload.mp4",
                    "metadata": {"video_bitrate_bps": 1_200_000},
                }],
            }

            staged = stage_upload_batch(
                batch,
                root / "upload-staging",
                normalize_bitrate=False,
            )

            self.assertEqual(Path(staged["items"][0]["upload_path"]).read_bytes(), b"original-video")
            self.assertFalse(staged["items"][0]["bitrate_normalized"])
            transcode.assert_not_called()

    def test_staging_replaces_same_size_stale_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            source.write_bytes(b"right")
            name = "upload.mp4"
            target = root / "staging" / "batch-01" / name
            target.parent.mkdir(parents=True)
            target.write_bytes(b"wrong")
            batch = {"index": 1, "items": [{"original_path": str(source), "upload_name": name}]}

            staged = stage_upload_batch(batch, root / "staging")

            self.assertEqual(source.read_bytes(), b"right")
            self.assertEqual(target.read_bytes(), b"right")
            self.assertEqual(staged["items"][0]["upload_path"], str(target))

    def test_staging_rejects_directory_in_place_of_upload_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            source.write_bytes(b"right")
            name = "upload.mp4"
            target = root / "staging" / "batch-01" / name
            target.mkdir(parents=True)
            batch = {"index": 1, "items": [{"original_path": str(source), "upload_name": name}]}

            with self.assertRaisesRegex(FileExistsError, "暂存位置被目录占用"):
                stage_upload_batch(batch, root / "staging")

    def test_staging_is_safe_when_same_batch_starts_concurrently(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            source.write_bytes(b"video-content")
            batch = {
                "index": 1,
                "items": [{"original_path": str(source), "upload_name": "upload.mp4"}],
            }

            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(
                    lambda _: stage_upload_batch(batch, root / "staging"),
                    range(8),
                ))

            target = root / "staging" / "batch-01" / "upload.mp4"
            self.assertEqual(target.read_bytes(), b"video-content")
            self.assertTrue(all(result["items"][0]["upload_path"] == str(target) for result in results))

    def test_staging_retries_a_transient_windows_file_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            source.write_bytes(b"video-content")
            batch = {
                "index": 1,
                "items": [{"original_path": str(source), "upload_name": "upload.mp4"}],
            }
            original_replace = os.replace
            attempts = []

            def locked_once(temporary, target):
                attempts.append((temporary, target))
                if len(attempts) == 1:
                    raise PermissionError("target is temporarily locked")
                return original_replace(temporary, target)

            with patch("src.upload.os.replace", side_effect=locked_once), patch("src.upload.time.sleep"):
                staged = stage_upload_batch(batch, root / "staging")

            self.assertEqual(len(attempts), 2)
            self.assertEqual(Path(staged["items"][0]["upload_path"]).read_bytes(), b"video-content")

    def test_confirmed_drama_mapping_and_uploader_are_remembered_locally(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "upload-preferences.json"

            remember_upload_preferences(
                path,
                drama_name="婚房门后的秘密",
                drama_platform_id="98765",
                director="王俨",
                uploader_initials="ZYY",
            )
            remember_upload_preferences(
                path,
                drama_name="婚房门后的秘密",
                drama_platform_id="87654",
                director="另一位编导",
                uploader_initials="ZYY",
            )
            preferences = load_upload_preferences(path)

            drama = preferences["dramas"]["婚房门后的秘密"]
            self.assertEqual(set(drama["ids"]), {"98765", "87654"})
            self.assertEqual(drama["ids"]["98765"]["director"], "王俨")
            self.assertEqual(drama["last_id"], "87654")
            self.assertEqual(preferences["uploader_initials"], "ZYY")

    def test_saved_upload_configuration_can_be_listed_and_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "upload-preferences.json"
            remember_upload_preferences(
                path,
                drama_name="婚房门后的秘密",
                drama_platform_id="41000339406",
                director="王仟",
                uploader_initials="ZYY",
            )

            entries = upload_preference_entries(load_upload_preferences(path))
            self.assertEqual(entries, [{
                "drama_name": "婚房门后的秘密",
                "drama_platform_id": "41000339406",
                "director": "王仟",
            }])

            self.assertTrue(forget_upload_preference(path, "婚房门后的秘密", "41000339406"))
            self.assertEqual(upload_preference_entries(load_upload_preferences(path)), [])


if __name__ == "__main__":
    unittest.main()
