import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget
from PySide6.QtTest import QTest

from src.desktop_widgets import AspectRatioContainer, PlatformPage
from src.upload import remember_upload_preferences


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
            self.assertGreaterEqual(page.upload_config_dialog.minimumWidth(), 480)
            self.assertIs(page.director.window(), page.upload_config_dialog)
            self.assertTrue(page.batch_selector.isHidden())
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
            self.assertFalse(page.batch_selector.isHidden())
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

    @patch(
        "src.desktop_widgets.navigate_edge_page",
        return_value={"ok": True, "action": "reload"},
    )
    def test_navigation_toolbar_refreshes_embedded_edge(self, navigate):
        page = PlatformPage({"platform_url": "https://market.wuread.cn/market-admin/login"})
        page.edge_target_ws_url = "ws://edge-page"

        QTest.mouseClick(page.reload_button, Qt.LeftButton)
        for _ in range(100):
            if navigate.called and "\u5df2\u5237\u65b0" in page.status.text():
                break
            QTest.qWait(10)

        navigate.assert_called_once_with("ws://edge-page", "reload")
        self.assertIn("\u5df2\u5237\u65b0", page.status.text())
        self.assertTrue(page.reload_button.isEnabled())
        page.deleteLater()

    def test_ineligible_material_is_not_added_to_upload_queue(self):
        page = PlatformPage({"platform_url": "https://market.wuread.cn/market-admin/"})
        rows = [{"video_id": "1", "input_error": "", "source": {"剧名": "测试"}}]
        records = {"1": {"status": "blocked", "download": "已下载", "video_path": "missing.mp4"}}

        page.set_materials(rows, records, {}, {"1"}, None)

        self.assertIn("0 条可上传", page.material_summary.text())
        self.assertFalse(page.prepare_button.isEnabled())
        self.assertTrue(page.edge_button.isHidden())
        self.assertEqual(page.internal_browser_button.text(), "打开平台")
        page.deleteLater()

    def test_development_edge_entry_is_opt_in(self):
        page = PlatformPage({
            "platform_url": "https://market.wuread.cn/market-admin/",
            "developer_edge_mode": True,
        })
        page.show()
        QTest.qWait(10)
        self.assertFalse(page.edge_button.isHidden())
        self.assertEqual(page.internal_browser_button.text(), "新建登录")
        page.deleteLater()

    @patch("src.desktop_widgets.QMessageBox.information")
    @patch("src.desktop_widgets.launch_embedded_edge", side_effect=RuntimeError("boom"))
    @patch("src.desktop_widgets.edge_target_ids", return_value=set())
    def test_edge_launch_failure_is_visible_and_retryable(self, _targets, _launch, message):
        page = PlatformPage({
            "platform_url": "https://market.wuread.cn/market-admin/",
            "developer_edge_mode": True,
        })

        page.open_edge_session()

        self.assertTrue(page.edge_button.isEnabled())
        self.assertIn("失败", page.status.text())
        message.assert_called_once()
        page.deleteLater()

    def test_platform_selection_populates_and_persists_upload_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            preferences = Path(folder) / "upload-preferences.json"
            page = PlatformPage({
                "platform_url": "https://market.wuread.cn/market-admin/",
                "upload_preferences_path": str(preferences),
            })

            page._platform_selection_finished({
                "ok": True,
                "director": "王仟",
                "dramaId": "41000339406",
                "dramaName": "婚房门后的秘密",
            })

            self.assertEqual(page.director.text(), "王仟")
            self.assertEqual(page.drama_id.currentText(), "41000339406")
            self.assertEqual(page.drama_name.text(), "婚房门后的秘密")
            saved = preferences.read_text(encoding="utf-8")
            self.assertIn("41000339406", saved)
            self.assertIn("王仟", saved)
            self.assertEqual(page.upload_config_dialog.history.count(), 2)
            self.assertEqual(
                page.upload_config_dialog.history.currentData()["drama_platform_id"],
                "41000339406",
            )
            page.deleteLater()

    @patch("src.desktop_widgets.QMessageBox.question", return_value=QMessageBox.Yes)
    def test_user_can_delete_saved_upload_configuration(self, _question):
        with tempfile.TemporaryDirectory() as folder:
            preferences = Path(folder) / "upload-preferences.json"
            page = PlatformPage({
                "platform_url": "https://market.wuread.cn/market-admin/",
                "upload_preferences_path": str(preferences),
            })
            page._platform_selection_finished({
                "ok": True,
                "director": "王仟",
                "dramaId": "41000339406",
                "dramaName": "婚房门后的秘密",
            })

            page.delete_upload_history()

            self.assertEqual(page.upload_config_dialog.history.count(), 1)
            self.assertNotIn("41000339406", preferences.read_text(encoding="utf-8"))
            self.assertEqual(page.drama_id.currentText(), "")
            self.assertEqual(page.director.text(), "")
            page.deleteLater()

    @patch("src.desktop_widgets.QMessageBox.information")
    @patch(
        "src.desktop_widgets.set_edge_file_input",
        return_value={
            "input_count": 1,
            "plugin_count": 1,
            "preview_count": 1,
            "video_preview_count": 1,
            "names": ["upload.mp4"],
        },
    )
    @patch(
        "src.desktop_widgets.evaluate_edge_page",
        return_value={"ok": True, "code": "FILE_INPUT_READY", "message": "ready"},
    )
    def test_embedded_edge_is_used_to_fill_form_and_select_files(self, _evaluate, set_files, message):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / "upload.mp4"
            video.write_bytes(b"video")
            page = PlatformPage({"platform_url": "https://market.wuread.cn/market-admin/"})
            page.edge_target_ws_url = "ws://edge-page"
            page.director.setText("王仟")
            page.drama_name.setText("婚房门后的秘密")
            page.drama_id.setEditText("41000339406")
            page.upload_batches = [{
                "index": 1,
                "items": [{"upload_path": str(video)}],
            }]

            page.fill_platform_form()
            for _ in range(100):
                if "upload.mp4" in page.status.text():
                    break
                QTest.qWait(10)

            message.assert_not_called()
            set_files.assert_called_once()
            self.assertIn("平台已接收 1 个文件并显示 1 个视频预览", page.status.text())
            self.assertIn("upload.mp4", page.status.text())
            page.deleteLater()

    def test_new_material_batch_requires_explicit_history_or_platform_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            preferences = root / "upload-preferences.json"
            video = root / "download.mp4"
            video.write_bytes(b"video")
            remember_upload_preferences(
                preferences,
                drama_name="婚房门后的秘密",
                drama_platform_id="41000339406",
                director="王仟",
                uploader_initials="ZYY",
            )
            page = PlatformPage({
                "platform_url": "https://market.wuread.cn/market-admin/",
                "upload_preferences_path": str(preferences),
            })

            page.set_materials(
                [{"video_id": "1", "input_error": "", "source": {"剧名": "婚房门后的秘密"}}],
                {"1": {"status": "sample_clear", "download": "已下载", "video_path": str(video)}},
                {},
                {"1"},
                root,
            )

            self.assertEqual(page.drama_name.text(), "婚房门后的秘密")
            self.assertEqual(page.drama_id.currentText(), "")
            self.assertEqual(page.director.text(), "")
            self.assertEqual(page.upload_config_dialog.history.currentIndex(), 0)
            page.deleteLater()

    def test_generate_upload_batch_button_runs_the_generation_flow(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video = root / "download.mp4"
            video.write_bytes(b"video")
            page = PlatformPage({
                "platform_url": "https://market.wuread.cn/market-admin/",
                "upload_preferences_path": str(root / "upload-preferences.json"),
            })
            page.set_materials(
                [{"video_id": "1", "input_error": "", "source": {"剧名": "婚房门后的秘密"}}],
                {"1": {"status": "sample_clear", "download": "已下载", "video_path": str(video)}},
                {},
                {"1"},
                root,
            )
            page.director.setText("白佳丽")
            page.drama_id.setEditText("41000339406")
            page.uploader_initials.setText("psk")
            page.upload_config_dialog.show()

            QTest.mouseClick(page.prepare_button, Qt.LeftButton)
            for _ in range(100):
                if page.upload_batches:
                    break
                QTest.qWait(10)

            self.assertEqual(len(page.upload_batches), 1)
            self.assertFalse(page.upload_config_dialog.isVisible())
            page.deleteLater()

    @patch("src.desktop_widgets.focus_edge_window")
    @patch("src.desktop_widgets.primary_mouse_button_pressed", return_value=True)
    @patch("src.desktop_widgets.QApplication.activeModalWidget")
    def test_modal_upload_dialog_prevents_edge_from_stealing_clicks(self, active_modal, _pressed, focus):
        page = PlatformPage({"platform_url": "https://market.wuread.cn/market-admin/"})
        page.edge_window_handle = 123
        page.edge_container = QWidget()
        page.edge_container.show()
        active_modal.return_value = page.upload_config_dialog

        page._sync_edge_input_focus()

        focus.assert_not_called()
        page.deleteLater()


if __name__ == "__main__":
    unittest.main()
