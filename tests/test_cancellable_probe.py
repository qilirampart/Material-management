import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from src.media import probe,validate_video,FFmpegCancelled
from src.material_variants import generate_variants,VariantOptions


class CancellableProbeTests(unittest.TestCase):
    def test_already_cancelled_probe_does_not_spawn_a_child(self):
        with patch('src.media.run') as run,self.assertRaises(FFmpegCancelled):probe('unused',should_stop=lambda:True)
        run.assert_not_called()

    def test_cancellable_probe_has_short_timeout_and_passes_stop_callback(self):
        stop=lambda:False
        payload={'streams':[{'codec_type':'video','width':720,'height':1280}], 'format':{'duration':'1'}}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fake.mp4';path.write_bytes(b'fake')
            with patch('src.media.run',return_value=json.dumps(payload)) as run:
                self.assertEqual(probe(path,should_stop=stop)['duration'],1)
                self.assertEqual(run.call_args.kwargs,{'should_stop':stop,'timeout':30})
            with patch('src.media.run',return_value=json.dumps(payload)) as run:
                probe(path);self.assertEqual(run.call_args.kwargs,{})

    def test_validation_probe_is_cancellable_before_decoding(self):
        stop=lambda:False
        with patch('src.media.probe',side_effect=FFmpegCancelled('stop')) as probing,patch('src.media.run') as run:
            with self.assertRaises(FFmpegCancelled):validate_video('unused',should_stop=stop)
        probing.assert_called_once_with('unused',should_stop=stop);run.assert_not_called()

    def test_cancel_during_source_probe_preserves_manifest_and_skips_encoding(self):
        with tempfile.TemporaryDirectory() as folder,patch('src.material_variants.probe',side_effect=FFmpegCancelled('stop')) as probing,patch('src.material_variants.run') as run:
            stop=lambda:False
            result=generate_variants([{'video_id':'1','path':'unused'}],folder,VariantOptions(mode='md5'),should_stop=stop)
            self.assertTrue(result['stopped']);self.assertFalse(result['failed']);run.assert_not_called()
            self.assertIs(probing.call_args.kwargs['should_stop'],stop)
