import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook
from src.batch import read_input
from src.task_input import parse_upload_drama_filename


class InputTests(unittest.TestCase):
    def test_filename_drama_info_extracts_platform_id_and_name(self):
        self.assertEqual(
            parse_upload_drama_filename("41000329324-垃圾桶里捡到爹.xlsx"),
            {"drama_platform_id": "41000329324", "drama_name": "垃圾桶里捡到爹"},
        )
        self.assertEqual(parse_upload_drama_filename("普通需求表.xlsx"), {})

    def test_real_input_with_incorrect_dimensions(self):
        path = Path(__file__).resolve().parents[1] / "懂小剧素材_婚房门后的秘密.xlsx"
        self.assertEqual(len(read_input(path)), 200)

    def test_preserves_duplicate_rows_and_rejects_mismatched_id(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.xlsx"
            w = Workbook()
            w.active.append(["剧名", "视频ID", "热度", "点赞数", "创建时间", "原始链接"])
            for id_, link in [("7681538825608236331", "7681538825608236331"),
                              ("7681538825608236331", "7681538825608236331"), ("123", "456")]:
                w.active.append(["测试", id_, 1, 2, "", "https://www.douyin.com/video/" + link])
            w.save(path)
            rows = read_input(path)
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0]["video_id"], rows[1]["video_id"])
            self.assertTrue(rows[2]["input_error"])

    def test_numeric_large_excel_id_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.xlsx"
            w = Workbook()
            w.active.append(["剧名", "视频ID", "热度", "点赞数", "创建时间", "原始链接"])
            w.active.append(["测试", 7681538825608236331, 1, 2, "", "https://www.douyin.com/video/7681538825608236331"])
            w.save(path)
            self.assertTrue(read_input(path)[0]["input_error"])
