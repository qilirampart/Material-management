import tempfile
import unittest
from pathlib import Path
from src.material_variants import VariantOptions,generate_variants,build_video_filter
from src.media import run,probe


class RegionEffectTests(unittest.TestCase):
    def test_regions_validate_and_are_applied_before_independent_crop_and_rotation(self):
        from src.region_effects import normalize_region
        region=normalize_region({'mode':'cover','x':10,'y':10,'w':20,'h':10,'start':1,'duration':2})
        options=VariantOptions(regions=[region],crop_mode='edges',crop_left=5,crop_top=10,rotation=90).validate()
        graph=build_video_filter(options,timeline_offset=1.5)
        self.assertLess(graph.index('drawbox'),graph.index('crop='))
        self.assertLess(graph.index('crop='),graph.index('transpose='))
        self.assertIn('t+1.5',graph)
        for invalid in ({'x':90,'w':20},{'mode':'repair','x':0},{'mode':'shell'},{'start':-1}):
            with self.assertRaises(ValueError):normalize_region(invalid)
        with self.assertRaises(ValueError):VariantOptions(crop_mode='edges',crop_left=60,crop_right=40).validate()

    def test_real_multiple_regions_crop_repair_and_rotated_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.mp4';rotated=root/'rotated.mp4'
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=30:duration=3',
                '-c:v','libx264',str(source)])
            run(['ffmpeg','-y','-v','error','-display_rotation:v:0','90','-i',str(source),'-c','copy',str(rotated)])
            self.assertEqual((probe(rotated)['display_width'],probe(rotated)['display_height']),(180,320))
            regions=[{'mode':'blur','x':10,'y':10,'w':20,'h':20},
                {'mode':'cover','x':40,'y':40,'w':15,'h':10,'start':.2,'duration':1},
                {'mode':'repair','x':70,'y':70,'w':10,'h':10}]
            for path in (source,rotated):
                result=generate_variants([{'video_id':path.stem,'path':str(path)}],root/'out',
                    VariantOptions(regions=regions,crop_mode='edges',crop_left=5,crop_right=10,crop_top=5,mirror=True))
                self.assertFalse(result['failed'],result['failed'])
                self.assertLessEqual(result['outputs'][0]['metadata']['video_bitrate_bps'],5000000)
