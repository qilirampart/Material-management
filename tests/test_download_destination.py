import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.download_support import Downloader


class DestinationTests(unittest.TestCase):
    def test_download_can_be_saved_on_another_volume(self):
        root = Path(__file__).resolve().parents[1] / "output"
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory() as source_folder, tempfile.TemporaryDirectory(dir=root) as target_folder:
            source = Path(source_folder) / "source.mp4"
            source.write_bytes(b"validated video bytes")
            target = Path(target_folder) / "videos" / "123.mp4"
            downloader = Downloader.__new__(Downloader)
            downloader.service = Mock()
            downloader.service.download_from_text.return_value = SimpleNamespace(local_path=str(source))
            with patch("src.media.validate_video", return_value={"audio": True}):
                self.assertTrue(downloader.download("https://www.douyin.com/video/123", target)["audio"])
            self.assertEqual(target.read_bytes(), b"validated video bytes")

    def test_download_uses_atomic_move_when_source_and_target_share_a_volume(self):
        root = Path(__file__).resolve().parents[1] / "output"
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as folder:
            source = Path(folder) / "source.mp4"
            source.write_bytes(b"validated video bytes")
            target = Path(folder) / "videos" / "123.mp4"
            downloader = Downloader.__new__(Downloader)
            downloader.service = Mock()
            downloader.service.download_from_text.return_value = SimpleNamespace(local_path=str(source))
            with patch("src.media.validate_video", return_value={"audio": True}), \
                 patch("src.download_support.shutil.copyfile") as copyfile:
                downloader.download("https://www.douyin.com/video/123", target)

            copyfile.assert_not_called()
            self.assertEqual(target.read_bytes(), b"validated video bytes")
