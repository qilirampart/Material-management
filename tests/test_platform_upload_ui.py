import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtTest import QTest

from src.desktop_widgets import AspectRatioContainer, PlatformPage


class PlatformUploadUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_selected_clear_material_prefills_drama_and_builds_staging_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video = root / "download.mp4"
            video.write_bytes(b"video")
            page = PlatformPage({
                "platform_url": "https://market.wuread.cn/market-admin/",
                "upload_preferences_path": str(root / "upload-preferences.json"),
            })
            rows = [{"video_id": "1", "input_error": "", "source": {"剧名": "婚房门后的秘密"}}]
            records = {"1": {"status": "sample_clear", "download": "已下载", "video_path": str(video)}}

            page.set_materials(rows, records, {}, {"1"}, root)

            self.assertEqual(page.drama_name.text(), "婚房门后的秘密")
            self.assertIn("1 条可上传", page.material_summary.text())
            page.director.setText("王俨")
            page.drama_id.setEditText("98765")
            page.uploader_initials.setText("ZYY")
            page.prepare_upload()
            for _ in range(100):
                if page.upload_batches:
                    break
                QTest.qWait(10)
            self.assertEqual(len(page.upload_batches), 1)
            self.assertTrue(Path(page.upload_batches[0]["items"][0]["upload_path"]).is_file())
            self.assertTrue(page.fill_button.isEnabled())
            page.deleteLater()

    def test_browser_stage_centers_a_sixteen_by_nine_view(self):
        child = QWidget()
        stage = AspectRatioContainer(child, maximum_width=960)
        stage.resize(800, 700)
        stage.show()
        QTest.qWait(20)

        self.assertEqual(child.width(), 768)
        self.assertEqual(child.height(), 432)
        self.assertEqual(child.x(), 16)
        self.assertEqual(child.y(), 134)
        stage.deleteLater()

    def test_ineligible_material_is_not_added_to_upload_queue(self):
        page = PlatformPage({"platform_url": "https://market.wuread.cn/market-admin/"})
        rows = [{"video_id": "1", "input_error": "", "source": {"剧名": "测试"}}]
        records = {"1": {"status": "blocked", "download": "已下载", "video_path": "missing.mp4"}}

        page.set_materials(rows, records, {}, {"1"}, None)

        self.assertIn("0 条可上传", page.material_summary.text())
        self.assertFalse(page.prepare_button.isEnabled())
        page.deleteLater()


if __name__ == "__main__":
    unittest.main()
