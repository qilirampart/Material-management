import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.material_variants import VariantOptions, generate_variants, validate_clip_ranges
from src.media import FFmpegCancelled, probe, run


class MaterialVariantTests(unittest.TestCase):
    def test_invalid_options_and_clip_ranges_are_rejected(self):
        for kwargs in ({'speed': 0}, {'variants': 0}, {'trim_start': -1}, {'background': 'bad'}):
            with self.assertRaises(ValueError):
                VariantOptions(**kwargs).validate()
        for ranges in ([{'start': 3, 'end': 2}], [{'start': 0, 'end': 11}],
                       [{'start': 0, 'end': 5}, {'start': 4, 'end': 6}]):
            with self.assertRaises(ValueError):
                validate_clip_ranges(ranges, 10)

    def test_md5_variant_is_playable_preserves_source_and_records_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source.mp4'
            run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i',
                 'testsrc2=size=160x240:rate=15:duration=2', '-c:v', 'libx264', str(source)])
            original = source.read_bytes()
            result = generate_variants(
                [{'video_id': '123', 'path': str(source), 'drama': '测试剧'}], root / 'out',
                VariantOptions(mode='md5', variants=2, uploader='PSK'),
            )
            self.assertEqual(len(result['outputs']), 2)
            hashes = {item['output_md5'] for item in result['outputs']}
            self.assertEqual(len(hashes), 2)
            for item in result['outputs']:
                self.assertNotEqual(item['source_md5'], item['output_md5'])
                self.assertEqual(Path(item['path']).parent.name, '改md5')
                self.assertIn('APP-繁花-王俨-改md5-测试剧-PSK-', Path(item['path']).name)
                self.assertAlmostEqual(probe(item['path'])['duration'], 2, delta=0.1)
            self.assertEqual(original, source.read_bytes())
            self.assertTrue(Path(result['manifest']).is_file())

    def test_stop_before_processing_and_bad_source_do_not_lose_other_items(self):
        with tempfile.TemporaryDirectory() as folder:
            result = generate_variants(
                [{'video_id': 'bad', 'path': 'missing.mp4', 'drama': '测试剧'}], folder,
                VariantOptions(mode='md5'), should_stop=lambda: True,
            )
            self.assertTrue(result['stopped'])
            self.assertEqual(result['outputs'], [])

    def test_failed_item_is_recorded_and_later_items_still_run(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source.mp4'
            run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i',
                 'testsrc2=size=160x240:rate=15:duration=1', '-c:v', 'libx264', str(source)])
            result = generate_variants([
                {'video_id': 'missing', 'path': str(Path(folder) / 'missing.mp4'), 'drama': '测试剧'},
                {'video_id': 'good', 'path': str(source), 'drama': '测试剧'},
            ], Path(folder) / 'out', VariantOptions(mode='md5'))
            self.assertEqual(result['failed'][0]['video_id'], 'missing')
            self.assertEqual(result['outputs'][0]['source_video_id'], 'good')

    @patch('src.material_variants.transcode_for_upload_bitrate', side_effect=FFmpegCancelled('stop'))
    @patch('src.material_variants.probe', return_value={'duration': 10})
    def test_cancel_active_encoding_does_not_start_next_video(self, _probe, transcode):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source.mp4'
            source.write_bytes(b'video')
            result = generate_variants([
                {'video_id': '1', 'path': str(source), 'drama': '测试剧'},
                {'video_id': '2', 'path': str(source), 'drama': '测试剧'},
            ], Path(folder) / 'out', VariantOptions())
            self.assertTrue(result['stopped'])
            self.assertFalse(result['failed'])
            self.assertEqual(transcode.call_count, 1)
            self.assertEqual(list((Path(folder) / 'out').rglob('*.mp4')), [])

    def test_micro_variant_changes_duration_and_satisfies_output_limits(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source.mp4'
            run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i',
                 'testsrc2=size=160x240:rate=15:duration=3', '-f', 'lavfi', '-i',
                 'sine=frequency=440:duration=3', '-c:v', 'libx264', '-c:a', 'aac',
                 '-shortest', str(source)])
            result = generate_variants(
                [{'video_id': '123', 'path': str(source), 'drama': '测试剧'}], root / 'out',
                VariantOptions(trim_start=0.2, trim_end=0.2, speed=1.03, background='blur'),
            )
            self.assertFalse(result['failed'], result['failed'])
            metadata = result['outputs'][0]['metadata']
            self.assertEqual((metadata['width'], metadata['height']), (720, 1280))
            self.assertLess(metadata['duration'], 3)
            self.assertTrue(metadata['audio'])
            self.assertGreater(metadata['video_bitrate_bps'], 3_500_000)
            self.assertLessEqual(metadata['video_bitrate_bps'], 5_000_000)
            self.assertLessEqual(metadata['file_size_bytes'], 522_240 * 1024)
