import tempfile
import unittest
from pathlib import Path
from tests import test_recreation_cleanup as fixtures
from src.recreation import RecreationBatch
from src.recreation_cleanup import plan_selection, execute_cleanup


class SelectionCleanupTests(unittest.TestCase):
    def fixture(self, root):
        return fixtures.CleanupTests().fixture(root)

    def test_one_product_selection_does_not_delete_other_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); w,b,raw,out,cover = self.fixture(root)
            plan = plan_selection(root, w.folders, [out])
            result = execute_cleanup(plan, w)
            self.assertEqual(result['deleted'], 2)
            self.assertFalse(out.exists()); self.assertFalse(cover.exists())
            self.assertTrue(raw.exists())
            self.assertTrue((b.folder/'recreation.json').exists())

    def test_directory_selection_protects_records_unknown_files_and_external_imports(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); w,b,raw,out,cover = self.fixture(root)
            unknown = b.folder/'notes.txt'; unknown.write_text('important')
            external = root/'imported.mp4'; external.write_bytes(b'original')
            b.add_local_sources([str(external)], b.state['dramas'][0])
            plan = plan_selection(root, w.folders, [root])
            execute_cleanup(plan, w)
            self.assertTrue(unknown.exists()); self.assertTrue(external.exists())
            self.assertTrue((b.folder/'recreation.json').exists())
            self.assertFalse(raw.exists()); self.assertFalse(out.exists())
            self.assertEqual(w.inputs, {'md5': [], 'micro': []})

    def test_cover_selection_includes_parent_product_to_keep_catalog_consistent(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); w,b,raw,out,cover=self.fixture(root)
            plan=plan_selection(root,w.folders,[cover])
            execute_cleanup(plan,w)
            self.assertFalse(out.exists()); self.assertFalse(cover.exists())
            self.assertEqual(RecreationBatch.load(b.folder).state['outputs'],[])

    def test_outside_root_is_rejected_even_if_registered(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); w,b,raw,out,cover=self.fixture(root)
            with self.assertRaises(ValueError):
                plan_selection(root/'other',w.folders,[raw])

    def test_staging_selection_preserves_products_and_historical_uploads(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); w,b,raw,out,cover=self.fixture(root)
            staging=b.folder/'upload-staging'/'batch-01'/'video.mp4'
            staging.parent.mkdir(parents=True); staging.write_bytes(b'staged')
            record=staging.parent/'plan.json'; record.write_text('{}')
            result=execute_cleanup(plan_selection(root,w.folders,[staging.parent]),w)
            self.assertEqual(result['deleted'],1)
            self.assertFalse(staging.exists()); self.assertTrue(record.exists())
            self.assertTrue(raw.exists()); self.assertTrue(out.exists())

    def test_selection_cannot_be_expanded_after_preview(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); w,b,raw,out,cover=self.fixture(root)
            plan=plan_selection(root,w.folders,[out])
            raw.write_bytes(b'new raw should remain')
            execute_cleanup(plan,w)
            self.assertTrue(raw.exists()); self.assertFalse(out.exists())

    def test_single_original_cleanup_preserves_other_queued_videos(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); w,b,raw,out,cover=self.fixture(root)
            b.record_page(b.state['dramas'][0],[{'id':'2','name':'another'}],1)
            second=b.state['sources'][-1]['video_id']
            w.queue[0]['identities'].append(second)
            execute_cleanup(plan_selection(root,w.folders,[raw]),w)
            self.assertEqual(w.queue,[{'folder':str(b.folder),'identities':[second]}])

    def test_unindexed_historical_file_is_recognized_without_registering_workspace(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); w,b,raw,out,cover=self.fixture(root)
            w.folders=[]
            plan=plan_selection(root,w.folders,[raw])
            self.assertEqual(plan['files'],1)
            self.assertEqual(w.folders,[])
            execute_cleanup(plan,w)
            self.assertFalse(raw.exists()); self.assertTrue(out.exists())

    def test_parent_directory_discovers_multiple_historical_batches(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); w,b,raw,out,cover=self.fixture(root)
            other=w.create('4200-another')[0]
            other.record_page(other.state['dramas'][0],[{'id':'9','name':'another'}],1)
            item=other.state['sources'][0]
            video=other.download_target(item); video.parent.mkdir(parents=True); video.write_bytes(b'other')
            item.update(path=str(video.resolve()),download_status='downloaded');other.save()
            plan=plan_selection(root,[],[root/'素材再创作'])
            self.assertEqual(plan['files'],4)
            self.assertEqual(len(plan['batches']),2)

    def test_unknown_video_without_batch_record_is_still_protected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); video=root/'unknown.mp4'; video.write_bytes(b'user file')
            w=fixtures.RecreationWorkspace(root/'prefs.json',root)
            plan=plan_selection(root,[],[video])
            self.assertEqual(plan['files'],0)
            execute_cleanup(plan,w)
            self.assertTrue(video.exists())
