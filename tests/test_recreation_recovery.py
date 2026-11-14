import json
import shutil
import tempfile
import unittest
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
from src.recreation import RecreationBatch
from src.material_variants import VariantOptions,generate_variants
from src.media import run,FFmpegCancelled
from src.recreation_recovery import inspect_manifest_recovery,commit_manifest_recovery


class RecoveryTests(unittest.TestCase):
    def fixture(self,root):
        source=root/'source.mp4'
        run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=size=240x240:rate=30:duration=1',
            '-c:v','libx264',str(source)])
        batch=RecreationBatch.create(root,[{'id':'4100','name':'测试剧'}]);batch.add_local_sources([str(source)],batch.state['dramas'][0])
        item=batch.state['sources'][0]
        result=generate_variants([item],batch.folder/'加工成品',VariantOptions(mode='md5'))
        self.assertFalse(result['failed']);return batch,Path(result['manifest']),result['outputs'][0]

    def test_real_orphan_recovery_duplicate_and_upload_metadata_from_source(self):
        with tempfile.TemporaryDirectory() as folder:
            batch,manifest,output=self.fixture(Path(folder))
            cover=Path(output['path']).with_suffix('.cover.png')
            run(['ffmpeg','-y','-v','error','-i',output['path'],'-frames:v','1',str(cover)])
            payload=json.loads(manifest.read_text(encoding='utf-8'));payload['outputs'][0]['upload_drama_info']={'drama_platform_id':'9999'}
            payload['outputs'][0]['metadata']['cover']={'path':'D:/old-location/cover.png','mode':'frame','duration':.2}
            manifest.write_text(json.dumps(payload),encoding='utf-8')
            plan=inspect_manifest_recovery(manifest)
            self.assertEqual(plan['entries'][0]['status'],'ready')
            self.assertEqual(RecreationBatch.load(batch.folder).state['outputs'],[])
            recovered,count=commit_manifest_recovery(plan,[0])
            self.assertEqual(count,1);self.assertEqual(recovered.state['outputs'][0]['path'],output['path'])
            self.assertEqual(recovered.state['outputs'][0]['upload_drama_info']['drama_platform_id'],'4100')
            self.assertEqual(recovered.state['outputs'][0]['metadata']['cover'],{'path':str(cover.resolve()),'mode':'frame','duration':.2})
            duplicate=inspect_manifest_recovery(manifest)
            self.assertEqual(duplicate['entries'][0]['status'],'duplicate')
            with self.assertRaises(ValueError):commit_manifest_recovery(duplicate,[0])

    def test_moved_batch_rebinds_only_its_own_run_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);batch,manifest,output=self.fixture(root)
            moved=root/'moved-batch';shutil.copytree(batch.folder,moved)
            local_manifest=moved/manifest.relative_to(batch.folder)
            plan=inspect_manifest_recovery(local_manifest)
            self.assertEqual(plan['entries'][0]['status'],'ready')
            recovered,count=commit_manifest_recovery(plan,[0]);self.assertEqual(count,1)
            self.assertTrue(Path(recovered.state['outputs'][0]['path']).is_relative_to(moved))
            self.assertEqual(RecreationBatch.load(batch.folder).state['outputs'],[])

    def test_missing_foreign_and_changed_files_never_enter_catalog(self):
        with tempfile.TemporaryDirectory() as folder:
            batch,manifest,output=self.fixture(Path(folder));original=json.loads(manifest.read_text(encoding='utf-8'))
            foreign=deepcopy(output);foreign['source_video_id']='foreign'
            missing=deepcopy(output);missing['path']=str(Path(output['path']).with_name('missing.mp4'))
            payload=dict(original,outputs=[foreign,missing,output]);manifest.write_text(json.dumps(payload),encoding='utf-8')
            plan=inspect_manifest_recovery(manifest)
            self.assertEqual([x['status'] for x in plan['entries']],['failed','failed','ready'])
            self.assertEqual(RecreationBatch.load(batch.folder).state['outputs'],[])
            bad=deepcopy(original);bad['outputs'][0]['output_md5']='0'*32
            manifest.write_text(json.dumps(bad),encoding='utf-8')
            invalid=inspect_manifest_recovery(manifest)
            self.assertEqual(invalid['entries'][0]['status'],'failed')
            self.assertIn('MD5',invalid['entries'][0]['reason'])
            manifest.write_text(json.dumps(original),encoding='utf-8');plan=inspect_manifest_recovery(manifest)
            with Path(output['path']).open('ab') as stream:stream.write(b'changed')
            with self.assertRaisesRegex(ValueError,'更改'):commit_manifest_recovery(plan,[0])
            self.assertEqual(RecreationBatch.load(batch.folder).state['outputs'],[])

    def test_write_failure_preserves_state_and_cancellation_is_read_only(self):
        with tempfile.TemporaryDirectory() as folder:
            batch,manifest,output=self.fixture(Path(folder));disk=(batch.folder/'recreation.json').read_bytes()
            with self.assertRaises(FFmpegCancelled):inspect_manifest_recovery(manifest,should_stop=lambda:True)
            plan=inspect_manifest_recovery(manifest)
            with patch('src.recreation.RecreationBatch.save',side_effect=OSError('read only')):
                with self.assertRaises(OSError):commit_manifest_recovery(plan,[0])
            self.assertEqual((batch.folder/'recreation.json').read_bytes(),disk)
            self.assertEqual(batch.state['outputs'],[]);self.assertTrue(Path(output['path']).is_file())
