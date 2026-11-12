import tempfile
import unittest
from pathlib import Path
from dataclasses import asdict
from unittest.mock import patch
from src.material_variants import VariantOptions
from src.media import run


class MicroCompositionTests(unittest.TestCase):
    def test_real_dynamic_background_pip_music_and_watermark_share_the_preview_plan(self):
        from src.material_variants import generate_variants,render_micro_preview,resolve_variant_options
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            source=root/'source.mp4';pip=root/'pip.mp4';image=root/'image.png';music=root/'music.wav'
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=30:duration=4',
                '-f','lavfi','-i','sine=frequency=440:duration=4','-c:v','libx264','-c:a','aac','-shortest',str(source)])
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=blue:size=100x100:rate=24:duration=1',
                '-c:v','libx264',str(pip)])
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=red:size=64x64','-frames:v','1',str(image)])
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i','sine=frequency=880:duration=1',str(music)])
            options=VariantOptions(variants=2,randomize=True,random_seed=99,color_adjust=False,
                random_ranges={'foreground_scale':[.65,.85],'speed':[1,1.1]},
                background_path=str(image),pip_path=str(pip),watermark_path=str(image),
                audio_mode='mix',music_path=str(music),zoom_mode='pulse',zoom_period=2,zoom_amount=.12)
            preview=render_micro_preview(source,root/'preview.mp4',options,start=1,seconds=2)
            frozen={(str(source.resolve()),1):VariantOptions(**preview['resolved_options'])}
            with patch('src.material_variants.resolve_variant_options',wraps=resolve_variant_options) as resolver:
                result=generate_variants([{'video_id':'demo','path':str(source),'drama':'test'}],root/'out',options,
                    resolved_plans=frozen)
            self.assertEqual(resolver.call_count,1)  # First version uses the preview, only version 2 is drawn.
            self.assertFalse(result['failed'],result['failed'])
            self.assertEqual(len(result['outputs']),2)
            self.assertEqual(preview['resolved_options'],result['outputs'][0]['options'])
            self.assertNotEqual(result['outputs'][0]['options']['speed'],result['outputs'][1]['options']['speed'])
            for output in result['outputs']:
                meta=output['metadata']
                self.assertTrue(meta['audio'])
                self.assertGreater(meta['duration'],3)
                self.assertAlmostEqual(meta['duration'],3.7/output['options']['speed'],delta=.15)
                self.assertGreater(meta['video_bitrate_bps'],3500000)
                self.assertLessEqual(meta['video_bitrate_bps'],5000000)
                self.assertLessEqual(meta['file_size_bytes'],522240*1024)
            for mode in ('in','out'):
                extra=render_micro_preview(source,root/(mode+'.mp4'),
                    VariantOptions(background_path=str(pip),pip_path=str(image),zoom_mode=mode),
                    start=1.5,seconds=1)
                self.assertAlmostEqual(extra['metadata']['duration'],1,delta=.15)

    def test_random_plan_is_reproducible_and_not_limited_to_color(self):
        from src.material_variants import resolve_variant_options
        options=VariantOptions(variants=3,color_adjust=False,randomize=True,random_seed=27,
            random_ranges={'foreground_scale':[.65,.9],'speed':[.95,1.1]})
        first=resolve_variant_options(options,'source-A',1)
        self.assertEqual(first,resolve_variant_options(options,'source-A',1))
        self.assertNotEqual(first.speed,resolve_variant_options(options,'source-A',2).speed)
        self.assertTrue(.65<=first.foreground_scale<=.9)
        self.assertFalse(first.randomize)
        options.validate()
        for ranges in ({'speed':[1.1,.9]},{'speed':[.7,1]},{'output_width':[500,1000]}):
            with self.assertRaises(ValueError):
                VariantOptions(randomize=True,random_ranges=ranges).validate()

    def test_old_favorites_are_upgraded_without_resetting_existing_values(self):
        from src.micro_presets import validate_settings,RECOMMENDED
        old=dict(RECOMMENDED)
        for key in ('zoom_mode','zoom_amount','zoom_period','background_path','pip_path','pip_scale',
                    'pip_x','pip_y','pip_opacity','randomize','random_seed','random_ranges','resource_pools'):
            old.pop(key,None)
        old['brightness']=.07
        upgraded=validate_settings(old)
        self.assertEqual(upgraded['brightness'],.07)
        self.assertEqual(upgraded['zoom_mode'],'none')

    def test_resource_pools_are_sorted_and_fail_explicitly_when_empty(self):
        from src.material_variants import resolve_variant_options
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ('a.png','b.jpg','ignored.txt'):(root/name).write_bytes(b'fixture')
            options=VariantOptions(randomize=True,resource_pools={'background_path':folder})
            value=resolve_variant_options(options,'source',1)
            self.assertIn(Path(value.background_path).name,('a.png','b.jpg'))
            with self.assertRaises(ValueError):
                resolve_variant_options(VariantOptions(randomize=True,
                    resource_pools={'music_path':folder},audio_mode='mix'),'source',1)
