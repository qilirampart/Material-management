import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from PIL import Image
from src.material_variants import VariantOptions,generate_variants,render_micro_preview,effective_clip_options
from src.media import run


class ClipSelectionTests(unittest.TestCase):
    def test_default_contract_and_explicit_range_boundaries(self):
        old=VariantOptions(trim_start=1,trim_end=2)
        self.assertIs(effective_clip_options(old,10),old)
        explicit=replace(old,clip_mode='range',range_start=3,range_duration=4)
        result=effective_clip_options(explicit,10)
        self.assertEqual((result.trim_start,result.trim_end),(3,3))
        self.assertEqual((explicit.trim_start,explicit.trim_end),(1,2))
        for settings in ({'clip_mode':'ai'},{'range_start':-1},{'range_duration':0},
                {'range_start':float('nan')}):
            with self.assertRaises(ValueError):VariantOptions(**settings).validate()
        with self.assertRaises(ValueError):effective_clip_options(replace(explicit,range_duration=8),10)

    def test_formal_and_preview_use_only_selected_middle_and_do_not_trim_twice(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'colors.mp4'
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i',
                "color=red:size=240x240:rate=30:duration=6,drawbox=color=lime:t=fill:enable='gte(t,2)*lt(t,4)',drawbox=color=blue:t=fill:enable='gte(t,4)'",
                '-f','lavfi','-i','sine=frequency=440:duration=6','-c:v','libx264','-c:a','aac','-shortest',str(source)])
            options=VariantOptions(clip_mode='range',range_start=2,range_duration=2,
                trim_start=30,trim_end=30,speed=1.2,color_adjust=False,
                output_width=240,output_height=240,foreground_scale=1,background='black')
            result=generate_variants([{'video_id':'colors','path':str(source)}],root/'out',options)
            self.assertFalse(result['failed'],result['failed']);output=result['outputs'][0]
            self.assertAlmostEqual(output['metadata']['duration'],2/1.2,delta=.12)
            self.assertTrue(output['metadata']['audio'])
            self.assertEqual(output['options']['trim_start'],2)
            self.assertEqual(output['options']['trim_end'],2)
            self.assertEqual(output['requested_options']['trim_start'],30)
            preview=render_micro_preview(source,root/'preview.mp4',options,start=0,seconds=10)
            self.assertEqual(preview['clip_start'],2)
            self.assertAlmostEqual(preview['metadata']['duration'],output['metadata']['duration'],delta=.1)
            for name,path in [('formal',output['path']),('preview',preview['path'])]:
                png=root/(name+'.png')
                run(['ffmpeg','-y','-v','error','-ss','1','-i',path,'-frames:v','1',str(png)])
                with Image.open(png) as image:self.assertGreater(image.convert('RGB').getpixel((120,120))[1],180)
            with self.assertRaises(ValueError):render_micro_preview(source,root/'past.mp4',options,start=4.5,seconds=1)
            frozen=VariantOptions(**preview['resolved_options'])
            replay=generate_variants([{'video_id':'colors','path':str(source)}],root/'replay',options,
                resolved_plans={(str(source.resolve()),1):frozen})
            self.assertFalse(replay['failed'],replay['failed'])
            self.assertAlmostEqual(replay['outputs'][0]['metadata']['duration'],2/1.2,delta=.12)
            # The tail belongs to the selected range, not the original blue ending.
            tail=render_micro_preview(source,root/'tail.mp4',replace(options,outro_path=str(source),outro_duration=.5),seconds=1,preview_section='tail')
            self.assertAlmostEqual(tail['metadata']['duration'],1.5,delta=.12)
            png=root/'tail-frame.png'
            run(['ffmpeg','-y','-v','error','-ss','0.2','-i',tail['path'],'-frames:v','1',str(png)])
            with Image.open(png) as image:self.assertGreater(image.convert('RGB').getpixel((120,120))[1],180)
            short=root/'short.mp4'
            run(['ffmpeg','-y','-v','error','-i',str(source),'-t','1','-c','copy',str(short)])
            mixed=generate_variants([{'video_id':'short','path':str(short)},{'video_id':'long','path':str(source)}],root/'mixed',options)
            self.assertEqual([item['video_id'] for item in mixed['failed']],['short'])
            self.assertIn('超出原片',mixed['failed'][0]['error'])
            self.assertEqual([item['source_video_id'] for item in mixed['outputs']],['long'])
