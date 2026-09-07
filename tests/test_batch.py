import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook
from src.batch import read_input


class InputTests(unittest.TestCase):
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
