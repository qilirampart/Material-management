import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from collections import namedtuple
from src.material_variants import generate_variants,VariantOptions


class ProcessingDiskBudgetTests(unittest.TestCase):
    def test_low_space_stops_before_encoding_and_keeps_manifest(self):
        usage=namedtuple('Usage','total used free')(1000,999,1)
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.mp4';source.write_bytes(b'fake')
            with patch('shutil.disk_usage',return_value=usage),patch('src.material_variants.probe',return_value={'duration':10,'file_size_bytes':4}),patch('src.material_variants.run') as encode:
                result=generate_variants([{'video_id':'1','path':str(source)}],Path(folder)/'out',VariantOptions(mode='md5'))
            self.assertTrue(result['stopped']);self.assertIn('空间不足',result['stop_reason'])
            self.assertFalse(result['failed']);encode.assert_not_called()
            self.assertTrue(Path(result['manifest']).is_file());self.assertTrue(source.is_file())

    def test_space_drop_between_outputs_preserves_first_and_stops_remainder(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.mp4';source.write_bytes(b'fake')
            from src.disk_budget import DiskSpaceLow
            def encode(command,**kwargs):Path(command[-1]).write_bytes(b'output')
            with patch('src.material_variants.require_disk_space',side_effect=[None,None,DiskSpaceLow('空间不足')]),patch('src.material_variants.probe',return_value={'duration':10,'file_size_bytes':4}),patch('src.material_variants.run',side_effect=encode),patch('src.material_variants.validate_video',return_value={'file_size_bytes':6}):
                result=generate_variants([{'video_id':'1','path':str(source)}],Path(folder)/'out',VariantOptions(mode='md5',variants=2))
            self.assertTrue(result['stopped']);self.assertEqual(len(result['outputs']),1)
            self.assertTrue(Path(result['outputs'][0]['path']).is_file());self.assertFalse(result['failed'])

    def test_estimate_uses_duration_versions_and_slowest_random_speed(self):
        from src.disk_budget import estimate_output_bytes
        base=VariantOptions(speed=1,trim_start=0,trim_end=0)
        slow=VariantOptions(speed=1,trim_start=0,trim_end=0,randomize=True,random_ranges={'speed':[.8,1.2]})
        self.assertGreater(estimate_output_bytes({'duration':100},slow),estimate_output_bytes({'duration':100},base))
