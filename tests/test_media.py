import tempfile
import unittest
from pathlib import Path

from src.media import describe_bitrate, describe_video, extract_frames, run, validate_video


class MediaTests(unittest.TestCase):
    def test_probe_reports_download_quality_information(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "quality.mp4"
            run([
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                "testsrc2=size=160x240:rate=10:duration=1", "-c:v", "libx264", str(path),
            ])

            metadata = validate_video(path)

            self.assertEqual((metadata["width"], metadata["height"]), (160, 240))
            self.assertAlmostEqual(metadata["frame_rate"], 10, places=1)
            self.assertEqual(metadata["video_codec"], "h264")
            self.assertGreater(metadata["total_bitrate_bps"], 0)
            self.assertEqual(metadata["file_size_bytes"], path.stat().st_size)
            description = describe_video(metadata)
            self.assertIn("160×240", description)
            self.assertIn("Mbps", description)
            self.assertIn("H264", description)

    def test_bitrate_description_uses_video_stream_and_3500_kbps_threshold(self):
        self.assertEqual(
            describe_bitrate({"video_bitrate_bps": 4_100_000, "total_bitrate_bps": 4_300_000}),
            "视频 4,100 kbps · 达标",
        )
        self.assertEqual(
            describe_bitrate({"video_bitrate_bps": 3_500_000, "total_bitrate_bps": 3_700_000}),
            "视频 3,500 kbps · 不足 3500",
        )

    def test_first_frame_and_one_second_intervals(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.mp4"
            run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x240:rate=10:duration=3.2",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=3.2", "-c:v", "libx264", "-c:a", "aac", str(path)])
            self.assertTrue(validate_video(path)["audio"])
            frames = extract_frames(path, Path(folder) / "frames")
            self.assertEqual([f["seconds"] for f in frames], [0.0, 1.0, 2.0])
            raw = Path(folder) / "first.png"
            run(["ffmpeg", "-y", "-v", "error", "-i", str(path), "-frames:v", "1", str(raw)])
            self.assertEqual(raw.read_bytes(), Path(frames[0]["path"]).read_bytes())

    def test_short_video_adjusts_timestamps(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "short.mp4"
            run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x240:rate=10:duration=0.6", str(path)])
            frames = extract_frames(path, Path(folder) / "frames")
            self.assertEqual(frames[0]["seconds"], 0)
            self.assertTrue(0 < frames[1]["seconds"] < frames[2]["seconds"] < 0.6)
