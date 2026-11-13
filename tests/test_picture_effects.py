import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from PIL import Image
from src.material_variants import VariantOptions,render_micro_preview
from src.media import run


class PictureEffectsTests(unittest.TestCase):
    def test_portrait_sources_fill_matching_landscape_cells_without_double_letterboxing(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'portrait.mp4'
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=lime:size=240x400:rate=30:duration=2',
                '-c:v','libx264',str(source)])
            options=VariantOptions(trim_start=0,trim_end=0,speed=1,color_adjust=False,foreground_scale=1,
                background='black',output_width=720,output_height=400,grid_layout='three_columns')
            result=render_micro_preview(source,root/'preview.mp4',options,seconds=1)
            png=root/'frame.png';run(['ffmpeg','-y','-v','error','-i',result['path'],'-frames:v','1',str(png)])
            with Image.open(png) as image:
                for x in (120,360,600):self.assertGreater(image.convert('RGB').getpixel((x,80))[1],180)

    def test_defaults_and_invalid_settings(self):
        VariantOptions().validate()
        for settings in ({'grid_layout':'random'},{'grid_fit':'stretch'},
                {'picture_style':'unknown'},{'border_width':-1},{'border_color':'red'},
                {'vignette':2}):
            with self.assertRaises(ValueError):VariantOptions(**settings).validate()

    def test_real_grid_monochrome_and_border_in_preview(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.mp4'
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i',
                'color=red:size=240x240:rate=30:duration=2,drawbox=x=120:y=0:w=120:h=240:color=blue:t=fill',
                '-c:v','libx264',str(source)])
            settings=VariantOptions(trim_start=0,trim_end=0,speed=1,color_adjust=False,
                output_width=240,output_height=240,foreground_scale=1,background='black',
                grid_layout='quad',picture_style='monochrome',border_width=8,border_color='00FF00')
            result=render_micro_preview(source,root/'preview.mp4',settings,seconds=1)
            png=root/'frame.png'
            run(['ffmpeg','-y','-v','error','-i',result['path'],'-frames:v','1',str(png)])
            with Image.open(png) as frame:
                image=frame.convert('RGB')
                r,g,b=image.getpixel((3,100));self.assertGreater(g,180);self.assertLess(r+b,50)
                # Four cells repeat the source's brighter left / darker right.
                for x,y in ((30,30),(150,30),(30,150),(150,150)):
                    left=image.getpixel((x,y));right=image.getpixel((x+60,y))
                    self.assertLess(max(left)-min(left),10)
                    self.assertGreater(left[0]-right[0],20)
            self.assertEqual(result['metadata']['width'],240)
            self.assertAlmostEqual(result['metadata']['duration'],1,delta=.1)

    def test_all_layouts_nondivisible_dimensions_styles_and_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.mp4'
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=red:size=240x240:rate=30:duration=2',
                '-f','lavfi','-i','sine=frequency=440:duration=2','-c:v','libx264','-c:a','aac','-shortest',str(source)])
            base=VariantOptions(trim_start=0,trim_end=0,speed=1,color_adjust=False,
                output_width=242,output_height=250,foreground_scale=1,background='black')
            for index,layout in enumerate(('two_rows','three_rows','two_columns','three_columns','quad')):
                with self.subTest(layout=layout):
                    options=replace(base,grid_layout=layout,grid_fit='fill' if index%2 else 'contain',
                        picture_style=('negative','sepia','original')[index%3],vignette=.2)
                    result=render_micro_preview(source,root/(layout+'.mp4'),options,seconds=1)
                    self.assertEqual((result['metadata']['width'],result['metadata']['height']),(242,250))
                    self.assertTrue(result['metadata']['audio'])
                    self.assertAlmostEqual(result['metadata']['duration'],1,delta=.1)
