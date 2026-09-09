import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.desktop import MainWindow


class CandidateTableUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow(restore=False)
        self.window.rows = [{
            "video_id": "7681538825608236331",
            "url": "https://www.douyin.com/video/7681538825608236331",
            "input_error": "",
            "source": {
                "剧名": "婚房门后的秘密",
                "原始链接": "https://www.douyin.com/video/7681538825608236331",
            },
        }]
        self.window.checked = {"7681538825608236331"}
        self.window.refresh_table()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()

    def test_candidate_table_shows_selection_number_id_and_original_url(self):
        headers = [
            self.window.table.horizontalHeaderItem(index).text()
            for index in range(self.window.table.columnCount())
        ]

        self.assertEqual(headers[:5], ["勾选", "编号", "视频 ID", "素材", "原视频链接"])
        self.assertEqual(self.window.table.item(0, 0).text(), "已选择")
        self.assertEqual(self.window.table.item(0, 0).checkState(), Qt.Checked)
        self.assertEqual(self.window.table.item(0, 1).text(), "1")
        self.assertEqual(self.window.table.item(0, 2).text(), "7681538825608236331")
        self.assertEqual(
            self.window.table.item(0, 4).text(),
            "https://www.douyin.com/video/7681538825608236331",
        )

    def test_unchecking_updates_the_visible_selection_label(self):
        self.window.table.item(0, 0).setCheckState(Qt.Unchecked)
        self.app.processEvents()

        self.assertEqual(self.window.table.item(0, 0).text(), "选择")
        self.assertNotIn("7681538825608236331", self.window.checked)
        self.assertIn("已勾选 0 条", self.window.selection_label.text())

    def test_original_url_is_searchable(self):
        self.window.search.setText("douyin.com/video/768153")
        self.app.processEvents()

        self.assertFalse(self.window.table.isRowHidden(0))

    def test_download_progress_updates_status_without_overwriting_identity(self):
        video_id = "7681538825608236331"
        title = self.window.table.item(0, 3).text()

        self.window.show_download_progress({
            "video_id": video_id,
            "received": 5 * 1048576,
            "total": 10 * 1048576,
            "percent": 50.0,
            "speed": 1048576,
        })

        self.assertEqual(self.window.table.item(0, 2).text(), video_id)
        self.assertEqual(self.window.table.item(0, 3).text(), title)
        self.assertEqual(self.window.table.item(0, 5).text(), "下载 50.0%")
        self.assertIn("1.0 MB/s", self.window.table.item(0, 5).toolTip())

    def test_stage_progress_updates_one_row_without_full_table_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            event_path = Path(folder) / "events.jsonl"
            event_path.write_text(json.dumps({
                "type": "progress",
                "video_id": "7681538825608236331",
                "stage": "抽帧检测",
            }) + "\n", encoding="utf-8")
            self.window.event_path = event_path
            self.window.event_offset = 0

            with patch.object(self.window, "refresh_table") as refresh:
                self.window.poll_events()

            refresh.assert_not_called()
            self.assertEqual(self.window.table.item(0, 7).text(), "抽帧检测…")
            self.assertEqual(self.window.table.item(0, 2).text(), "7681538825608236331")

    def test_downloaded_video_quality_is_visible_in_candidate_table(self):
        self.window.records = {
            "7681538825608236331": {
                "download": "已下载",
                "metadata": {
                    "width": 1080,
                    "height": 1920,
                    "frame_rate": 30,
                    "total_bitrate_bps": 4_800_000,
                    "video_codec": "h264",
                    "file_size_bytes": 12 * 1048576,
                },
            },
        }

        self.window.refresh_table()

        self.assertEqual(self.window.table.horizontalHeaderItem(6).text(), "码率 / 视频信息")
        self.assertEqual(self.window.table.horizontalHeader().visualIndex(6), 4)
        quality = self.window.table.item(0, 6).text()
        self.assertIn("总 4,800 kbps · 达标", quality)
        self.assertIn("1080×1920", quality)
        self.assertIn("4.80 Mbps", quality)
        self.assertIn("30fps", quality)

    def test_upload_bitrate_enhancement_action_is_visible(self):
        self.assertTrue(self.window.bitrate_button.isVisibleTo(self.window))
        self.assertEqual(self.window.bitrate_button.text(), "提升选中低码率视频")

    def test_bitrate_progress_shows_current_item_and_queue_position(self):
        self.window.show_bitrate_progress({
            "phase": "started",
            "video_id": "7681538825608236331",
            "index": 2,
            "total": 5,
        })

        self.assertEqual(self.window.download_bar.maximum(), 5)
        self.assertEqual(self.window.download_bar.value(), 1)
        self.assertEqual(self.window.download_bar.format(), "第 2 / 5 个")
        self.assertIn("7681538825608236331", self.window.work_detail.text())

    def test_backfilled_quality_is_displayed_and_saved_for_old_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "results.json").write_text("{}", encoding="utf-8")
            self.window.folder = root
            self.window.records = {
                "7681538825608236331": {
                    "download": "已下载",
                    "video_path": str(root / "video.mp4"),
                    "metadata": {"width": 576, "height": 1024},
                },
            }
            metadata = {
                "width": 576,
                "height": 1024,
                "video_bitrate_bps": 468_000,
                "total_bitrate_bps": 528_000,
            }

            self.window.apply_quality_metadata({
                "folder": str(root.resolve()),
                "metadata": {"7681538825608236331": metadata},
            })

            self.assertIn("视频 468 kbps", self.window.table.item(0, 6).text())
            saved = json.loads((root / "results.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["records"]["7681538825608236331"]["metadata"], metadata)

    def test_bitrate_result_only_updates_the_batch_that_started_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "results.json").write_text("{}", encoding="utf-8")
            self.window.folder = root
            self.window.records = {"7681538825608236331": {}}
            update = {
                "bitrate_enhanced_path": str(root / "enhanced.mp4"),
                "bitrate_enhanced_metadata": {"video_bitrate_bps": 4_200_000},
            }

            self.window.apply_enhanced_bitrates({
                "folder": str(root.resolve()),
                "updates": {"7681538825608236331": update},
                "failed": {},
            })
            self.assertEqual(
                self.window.records["7681538825608236331"]["bitrate_enhanced_path"],
                update["bitrate_enhanced_path"],
            )

            self.window.apply_enhanced_bitrates({
                "folder": str((root / "other-batch").resolve()),
                "updates": {
                    "7681538825608236331": {"bitrate_enhanced_path": "stale.mp4"},
                },
                "failed": {},
            })
            self.assertEqual(
                self.window.records["7681538825608236331"]["bitrate_enhanced_path"],
                update["bitrate_enhanced_path"],
            )

    def test_batch_selection_supports_first_n_invert_and_to_end(self):
        for offset in range(1, 5):
            video_id = str(7681538825608236331 + offset)
            url = f"https://www.douyin.com/video/{video_id}"
            self.window.rows.append({
                "video_id": video_id,
                "url": url,
                "input_error": "",
                "source": {"剧名": "婚房门后的秘密", "原始链接": url},
            })
        self.window.checked.clear()
        self.window.refresh_table()

        self.window.selection_count.setValue(2)
        self.window.select_first_rows()
        self.assertEqual(self.window.checked, {
            "7681538825608236331",
            "7681538825608236332",
        })

        self.window.invert_visible_selection()
        self.assertEqual(self.window.checked, {
            "7681538825608236333",
            "7681538825608236334",
            "7681538825608236335",
        })

        self.window.table.setCurrentCell(3, 2)
        self.window.select_from_current_to_end()
        self.assertEqual(self.window.checked, {
            "7681538825608236334",
            "7681538825608236335",
        })

    def test_bulk_selection_does_not_rebuild_the_full_table(self):
        self.window.checked.clear()
        self.window.selection_count.setValue(1)

        with patch.object(self.window, "refresh_table") as refresh:
            self.window.select_first_rows()

        refresh.assert_not_called()
        self.assertEqual(self.window.checked, {"7681538825608236331"})
        self.assertEqual(self.window.table.item(0, 0).checkState(), Qt.Checked)

    def test_remove_checked_materials_keeps_unselected_rows(self):
        second = {
            "video_id": "7681538825608236332",
            "url": "https://www.douyin.com/video/7681538825608236332",
            "input_error": "",
            "source": {"剧名": "婚房门后的秘密", "原始链接": ""},
        }
        self.window.rows.append(second)
        self.window.remove_checked_rows()

        self.assertEqual([row["video_id"] for row in self.window.rows], [second["video_id"]])
        self.assertEqual(self.window.checked, set())


if __name__ == "__main__":
    unittest.main()
