import tempfile
import unittest
from pathlib import Path

from src.update import UpdateError, check_for_update, download_update, version_key


class FakeResponse:
    def __init__(self, payload=None, chunks=(), headers=None):
        self.payload = payload
        self.chunks = chunks
        self.headers = headers or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload

    def iter_content(self, chunk_size):
        return iter(self.chunks)


class UpdateTests(unittest.TestCase):
    def test_version_key_accepts_v_prefix(self):
        self.assertEqual(version_key("v0.3.7"), (0, 3, 7))
        with self.assertRaises(UpdateError):
            version_key("release-3")

    def test_check_selects_windows_installer(self):
        payload = {
            "tag_name": "v0.3.8",
            "html_url": "https://github.com/qilirampart/Material-management/releases/tag/v0.3.8",
            "assets": [
                {"name": "DianzhongMaterialAssistant-macos-0.3.8.zip", "size": 2, "browser_download_url": "https://github.com/qilirampart/Material-management/releases/download/v0.3.8/DianzhongMaterialAssistant-macos-0.3.8.zip"},
                {"name": "DianzhongMaterialAssistant-Setup-0.3.8.exe", "size": 3, "browser_download_url": "https://github.com/qilirampart/Material-management/releases/download/v0.3.8/DianzhongMaterialAssistant-Setup-0.3.8.exe"},
            ],
        }
        found = check_for_update(current_version="0.3.7", system="Windows", request_get=lambda *args, **kwargs: FakeResponse(payload))
        self.assertTrue(found["update_available"])
        self.assertEqual(found["asset"]["name"], "DianzhongMaterialAssistant-Setup-0.3.8.exe")

    def test_download_update_writes_atomically_and_reports_progress(self):
        updates = []
        with tempfile.TemporaryDirectory() as directory:
            target = download_update(
                {"name": "update.exe", "url": "https://github.com/qilirampart/Material-management/releases/download/v0.3.8/update.exe", "size": 3},
                Path(directory),
                progress=updates.append,
                request_get=lambda *args, **kwargs: FakeResponse(chunks=[b"a", b"bc"], headers={"content-length": "3"}),
            )
            self.assertEqual(target.read_bytes(), b"abc")
            self.assertFalse(target.with_suffix(".exe.part").exists())
        self.assertEqual(updates[-1]["downloaded"], 3)
