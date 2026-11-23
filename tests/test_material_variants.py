import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.material_variants import VariantOptions, generate_variants, validate_clip_ranges, build_video_filter
from src.media import FFmpegCancelled, probe, run


class MaterialVariantTests(unittest.TestCase):
    def test_mac_supplemental_chinese_font_is_available_without_pingfang(self):
        from src.material_variants import _font_file
        font = Path('/System/Library/Fonts/Supplemental/Songti.ttc')
        with patch.object(Path, 'is_file', lambda path: path == font):
            self.assertEqual(_font_file(), font)

    def test_preview_is_short_uses_current_effects_and_does_not_create_products(self):
        from src.material_variants import render_micro_preview
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root/'source.mp4'
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=30:duration=5',
                 '-c:v','libx264',str(source)])
            result = render_micro_preview(source, root/'preview.mp4',
                VariantOptions(output_width=1280,output_height=720,audio_mode='mute'), start=1, seconds=2)
            self.assertEqual((result['metadata']['width'],result['metadata']['height']),(1280,720))
            self.assertAlmostEqual(result['metadata']['duration'],2,delta=.15)
            self.assertEqual(result['clip_start'],1)
            self.assertFalse(list(root.rglob('manifest.json')))
            with self.assertRaises(ValueError):
                render_micro_preview(source, root/'bad.mp4', VariantOptions(), start=10)

    def test_extended_micro_filters_watermark_music_mask_and_mute_render_real_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, image, music = root/'source.mp4', root/'watermark.png', root/'music.wav'
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=30:duration=4',
                 '-f','lavfi','-i','sine=frequency=440:duration=4','-c:v','libx264','-c:a','aac','-shortest',str(source)])
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=red:size=64x64','-frames:v','1',str(image)])
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i','sine=frequency=880:duration=1',str(music)])
            item = {'video_id':'extended','path':str(source),'drama':'扩展测试'}
            cases = [VariantOptions(output_width=1280,output_height=720,mirror=True,rotation=90,
                        crop_percent=2,sharpen=.3,denoise=1,output_fps=24,drop_every=25,
                        title='测试标题',title_position='bottom',watermark_path=str(image),
                        audio_mode='mix',music_path=str(music),mask_mode='cover',mask_x=5,mask_y=5),
                     VariantOptions(audio_mode='mute',mask_mode='blur',mask_x=5,mask_y=5,
                                    rotation=90,mask_w=1,mask_h=1),
                     VariantOptions(audio_mode='replace',music_path=str(music),background='black',output_fps=25)]
            for options in cases:
                result = generate_variants([item], root/'out', options)
                self.assertFalse(result['failed'], result['failed'])
                meta = result['outputs'][0]['metadata']
                self.assertEqual((meta['width'],meta['height']), (options.output_width,options.output_height))
                self.assertEqual(meta['audio'], options.audio_mode!='mute')
                self.assertLess(abs(meta['duration']-(4-.3)/1.02), .15)
                self.assertGreater(meta['video_bitrate_bps'],3_500_000)
                self.assertLessEqual(meta['video_bitrate_bps'],5_000_000)
                if options.output_fps:
                    self.assertEqual(meta['frame_rate'],options.output_fps)

    def test_extended_options_validate_and_build_real_filters(self):
        options = VariantOptions(output_width=1280, output_height=720, foreground_scale=.85,
            vertical_position=.25, mirror=True, rotation=90, crop_percent=2,
            brightness=.02, contrast=1.05, saturation=1.1, sharpen=.3, denoise=2,
            output_fps=24, drop_every=30, title='示例', title_position='bottom', title_size=32,
            mask_mode='cover', mask_x=5, mask_y=5, mask_w=15, mask_h=10).validate()
        graph = build_video_filter(options, text_path=Path('title.txt'), source_metadata={'width': 1920, 'height': 1080, 'frame_rate': 30})
        for expected in ('hflip', 'transpose=1', 'crop=', 'drawbox=', 'unsharp=', 'hqdn3d=', 'fps=24', '1280:720'):
            self.assertIn(expected, graph)
        for kwargs in ({'output_width': 721}, {'foreground_scale': 1.1}, {'rotation': 45},
                       {'drop_every': 1}, {'mask_mode': 'cover', 'mask_x': 95, 'mask_w': 20}, {'title_position': 'bad'},
                       {'audio_mode': 'replace'}, {'brightness': float('nan')}):
            with self.assertRaises(ValueError):
                VariantOptions(**kwargs).validate()

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
            self.assertEqual(result['failed'][0]['stage'], '读取原片')
            self.assertIn('原片不存在', result['failed'][0]['error'])
            self.assertEqual(result['outputs'][0]['source_video_id'], 'good')

    def test_retry_runs_only_requested_versions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root/'source.mp4'
            run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i',
                 'testsrc2=size=160x240:rate=15:duration=1', '-c:v', 'libx264', str(source)])
            item = {'video_id': 'sample', 'path': str(source), 'drama': '测试剧'}
            result = generate_variants([item], root/'out', VariantOptions(mode='md5', variants=3),
                                       versions_by_id={'sample': [2]})
            self.assertFalse(result['failed'])
            self.assertEqual([item['version'] for item in result['outputs']], [2])

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
