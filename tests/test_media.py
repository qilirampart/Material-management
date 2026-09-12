import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.media import (
    FFmpegError,
    describe_bitrate,
    describe_video,
    effective_video_bitrate_bps,
    extract_frames,
    preferred_hardware_h264_encoder,
    run,
    transcode_for_upload_bitrate,
    validate_video,
)


class MediaTests(unittest.TestCase):
    def test_prefers_nvidia_then_intel_then_amd_hardware_h264_encoder(self):
        output = "\n".join([
            " V....D h264_amf            AMD AMF H.264 Encoder",
            " V....D h264_qsv            H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (Intel Quick Sync Video acceleration)",
            " V....D h264_nvenc          NVIDIA NVENC H.264 encoder",
        ])

        self.assertEqual(preferred_hardware_h264_encoder(output), "h264_nvenc")
        self.assertEqual(preferred_hardware_h264_encoder(" V....D h264_qsv Intel"), "h264_qsv")
        self.assertIsNone(preferred_hardware_h264_encoder(" V....D libx264 H.264"))

    @patch("src.media.validate_video")
    @patch("src.media.run")
    @patch("src.media.probe")
    def test_bitrate_transcode_reports_encoding_and_validation_phases(
        self, probe_video, run_ffmpeg, validate_video
    ):
        probe_video.return_value = {"duration": 10}
        validate_video.return_value = {"video_bitrate_bps": 4_200_000}
        phases = []
        with tempfile.TemporaryDirectory() as folder:
            with patch("src.media.hardware_h264_encoder", return_value=None):
                transcode_for_upload_bitrate(
                    Path(folder) / "source.mp4",
                    Path(folder) / "output.mp4",
                    progress=phases.append,
                )

        self.assertEqual(phases, ["encoding", "validating"])
        run_ffmpeg.assert_called_once()

    @patch("src.media.validate_video")
    @patch("src.media.run")
    @patch("src.media.probe")
    @patch("src.media.hardware_h264_encoder", return_value="h264_nvenc")
    def test_bitrate_transcode_falls_back_to_cpu_when_hardware_encoder_fails(
        self, hardware_encoder, probe_video, run_ffmpeg, validate_video
    ):
        probe_video.return_value = {"duration": 10}
        validate_video.return_value = {"video_bitrate_bps": 4_200_000}
        run_ffmpeg.side_effect = [FFmpegError("NVENC unavailable"), ""]
        with tempfile.TemporaryDirectory() as folder:
            metadata = transcode_for_upload_bitrate(
                Path(folder) / "source.mp4", Path(folder) / "output.mp4"
            )

        self.assertEqual(run_ffmpeg.call_count, 2)
        self.assertIn("h264_nvenc", run_ffmpeg.call_args_list[0].args[0])
        self.assertIn("libx264", run_ffmpeg.call_args_list[1].args[0])
        self.assertEqual(metadata["transcode"]["video_encoder"], "libx264")
        self.assertFalse(metadata["transcode"]["hardware_accelerated"])

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

    def test_upload_transcode_exceeds_threshold_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            output = root / "upload.mp4"
            run([
                "ffmpeg", "-y", "-v", "error",
                "-f", "lavfi", "-i", "testsrc2=size=160x240:rate=15:duration=2",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                "-c:v", "libx264", "-b:v", "300k", "-c:a", "aac", "-shortest", str(source),
            ])
            original = source.read_bytes()

            metadata = transcode_for_upload_bitrate(source, output)

            self.assertEqual(source.read_bytes(), original)
            self.assertTrue(metadata["audio"])
            self.assertEqual(metadata["video_codec"], "h264")
            self.assertGreater(effective_video_bitrate_bps(metadata), 3_500_000)

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
