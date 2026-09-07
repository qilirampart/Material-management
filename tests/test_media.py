import tempfile
import unittest
from pathlib import Path

from src.media import extract_frames, run, validate_video


class MediaTests(unittest.TestCase):
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
