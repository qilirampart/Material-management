import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class BitrateBatchPersistenceTests(unittest.TestCase):
    @patch("src.upload.transcode_for_upload_bitrate")
    def test_each_success_is_saved_even_when_another_item_fails(self, transcode):
        from src.desktop import enhance_batch_bitrates

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
            (root / "results.json").write_text(
                json.dumps({"records": records}),
                encoding="utf-8",
            )

            def convert(_source, output):
                if Path(output).stem == "2":
                    raise RuntimeError("broken input")
                Path(output).write_bytes(b"enhanced-video")
                return {"video_bitrate_bps": 4_200_000}

            transcode.side_effect = convert

            result = enhance_batch_bitrates(root, records, ["1", "2"])

            saved = json.loads((root / "results.json").read_text(encoding="utf-8"))
            self.assertIn("bitrate_enhanced_path", saved["records"]["1"])
            self.assertNotIn("bitrate_enhanced_path", saved["records"]["2"])
            self.assertEqual(set(result["updates"]), {"1"})
            self.assertEqual(result["failed"], {"2": "RuntimeError"})
            self.assertEqual(result["folder"], str(root.resolve()))


if __name__ == "__main__":
    unittest.main()
