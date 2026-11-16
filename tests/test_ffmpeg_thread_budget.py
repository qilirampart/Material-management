import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from src.media import transcode_for_upload_bitrate,validate_video


class FFmpegThreadBudgetTests(unittest.TestCase):
    def test_codec_and_filters_are_bounded_for_software_and_hardware(self):
        for encoder in (None,'h264_nvenc'):
            with self.subTest(encoder=encoder),tempfile.TemporaryDirectory() as folder,patch('src.media.os.cpu_count',return_value=32),patch('src.media.probe',return_value={'duration':10}),patch('src.media.hardware_h264_encoder',return_value=encoder),patch('src.media.validate_video',return_value={'video_bitrate_bps':4200000}),patch('src.media.run') as run:
                transcode_for_upload_bitrate(Path(folder)/'in.mp4',Path(folder)/'out.mp4')
                command=run.call_args.args[0]
                self.assertEqual(command[command.index('-filter_complex_threads')+1],'4')
                self.assertEqual(command[command.index('-filter_threads')+1],'4')
                positions=[i for i,value in enumerate(command) if value=='-threads']
                self.assertGreaterEqual(len(positions),2)
                self.assertTrue(all(command[i+1]=='4' for i in positions))
                self.assertLess(positions[0],command.index('-i'))

    def test_validation_decoder_respects_low_core_machines(self):
        with patch('src.media.os.cpu_count',return_value=2),patch('src.media.probe',return_value={}),patch('src.media.run') as run:
            validate_video('unused')
        command=run.call_args.args[0]
        self.assertEqual(command[command.index('-threads')+1],'2')
