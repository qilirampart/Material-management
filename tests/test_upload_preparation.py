import tempfile
import unittest
from datetime import date
from pathlib import Path

from src.upload import build_upload_plan, eligible_materials, suggested_drama_name


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


if __name__ == "__main__":
    unittest.main()
