import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from src.recreation import RecreationBatch
from src.recreation_workspace import RecreationWorkspace
from src.recreation_cleanup import plan_cleanup, execute_cleanup


class CleanupTests(unittest.TestCase):
    def fixture(self, root):
        w = RecreationWorkspace(root/'prefs.json', root)
        b = w.create('4100-test')[0]
        b.record_page(b.state['dramas'][0], [{'id': '1', 'name': '二创'}], 1)
        s = b.state['sources'][0]
        raw = b.download_target(s); raw.parent.mkdir(parents=True); raw.write_bytes(b'original')
        s.update(path=str(raw.resolve()), download_status='downloaded')
        out = b.folder/'加工成品'/'run'/'test'/'改md5'/'one.mp4'
        out.parent.mkdir(parents=True); out.write_bytes(b'product')
        cover = out.with_suffix('.cover.png'); cover.write_bytes(b'cover')
        b.add_outputs([{'path': str(out), 'drama': 'test', 'mode': 'md5', 'metadata': {}}])
        w.add_inputs('md5', b.folder, [s['video_id']]); w.add_inputs('micro', b.folder, [s['video_id']])
        w.enqueue(b.folder, [s['video_id']])
        return w, b, raw, out, cover

    def test_products_deleted_without_touching_original_or_batch_record(self):
        with tempfile.TemporaryDirectory() as folder:
            w,b,raw,out,cover = self.fixture(Path(folder))
            result = execute_cleanup(plan_cleanup([b.folder], 'products'), w)
            self.assertEqual(result['deleted'], 2)
            self.assertFalse(out.exists()); self.assertFalse(cover.exists()); self.assertTrue(raw.exists())
            self.assertEqual(RecreationBatch.load(b.folder).state['outputs'], [])
            self.assertEqual(len(w.inputs['md5']), 1)

    def test_original_deletion_syncs_both_processing_lists_and_queue_not_products(self):
        with tempfile.TemporaryDirectory() as folder:
            w,b,raw,out,cover = self.fixture(Path(folder))
            execute_cleanup(plan_cleanup([b.folder], 'originals'), w)
            self.assertFalse(raw.exists()); self.assertTrue(out.exists())
            self.assertEqual(w.inputs, {'md5': [], 'micro': []}); self.assertEqual(w.queue, [])
            self.assertEqual(RecreationBatch.load(b.folder).state['sources'][0]['download_status'], 'pending')
            self.assertEqual(RecreationBatch.load(b.folder).state['sources'][0]['path'], '')

    def test_external_local_and_forged_external_product_are_never_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); w,b,raw,out,cover=self.fixture(root)
            outside=root/'external.mp4'; outside.write_bytes(b'user-original')
            b.add_local_sources([str(outside)], b.state['dramas'][0])
            b.add_outputs([{'path':str(outside),'drama':'test','mode':'micro','metadata':{}}])
            plan=plan_cleanup([b.folder], 'all')
            self.assertEqual(plan['protected'], 2)
            execute_cleanup(plan, w)
            self.assertEqual(outside.read_bytes(), b'user-original')

    def test_changed_record_or_file_after_confirmation_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            w,b,raw,out,cover=self.fixture(Path(folder)); plan=plan_cleanup([b.folder], 'products')
            out.write_bytes(b'a changed product')
            result=execute_cleanup(plan,w)
            self.assertTrue(result['errors']); self.assertTrue(out.exists())
            self.assertEqual(len(RecreationBatch.load(b.folder).state['outputs']),1)
            plan=plan_cleanup([b.folder], 'products'); b.state['note']='changed'; b.save()
            result=execute_cleanup(plan,w); self.assertTrue(result['errors']); self.assertTrue(out.exists())

    def test_failed_delete_keeps_record_and_repeated_cleanup_is_safe(self):
        with tempfile.TemporaryDirectory() as folder:
            w,b,raw,out,cover=self.fixture(Path(folder))
            unlink=Path.unlink
            def locked(p,*a,**kw):
                if p==out.resolve(): raise PermissionError('locked')
                return unlink(p,*a,**kw)
            with patch.object(Path,'unlink',locked):
                result=execute_cleanup(plan_cleanup([b.folder], 'products'),w)
            self.assertTrue(result['errors']); self.assertTrue(out.exists()); self.assertTrue(cover.exists())
            execute_cleanup(plan_cleanup([b.folder], 'products'),w)
            again=execute_cleanup(plan_cleanup([b.folder], 'products'),w)
            self.assertEqual(again['deleted'],0)

    def test_forget_missing_batch_removes_only_references_and_rolls_back_on_save_error(self):
        with tempfile.TemporaryDirectory() as folder:
            w,b,raw,out,cover=self.fixture(Path(folder)); refs=list(w.inputs['md5'])
            with patch.object(w,'save',side_effect=OSError('disk')):
                with self.assertRaises(OSError): w.forget_batches([str(b.folder)])
            self.assertEqual(w.inputs['md5'],refs)
            w.forget_batches([str(b.folder)])
            self.assertEqual(w.folders,[]);self.assertEqual(w.queue,[]);self.assertEqual(w.last_batch,'')
            self.assertTrue(raw.exists());self.assertTrue(out.exists())

    def test_external_file_already_removed_is_reconciled_without_other_batch_loss(self):
        with tempfile.TemporaryDirectory() as folder:
            w,b,raw,out,cover=self.fixture(Path(folder));raw.unlink();out.unlink()
            result=execute_cleanup(plan_cleanup([b.folder], 'all'),w)
            self.assertEqual(result['deleted'],1)
            self.assertGreaterEqual(result['missing'],2)
            self.assertEqual(RecreationBatch.load(b.folder).state['outputs'],[])

    def test_batch_record_save_failure_reports_partial_work_and_does_not_clear_input_references(self):
        with tempfile.TemporaryDirectory() as folder:
            w,b,raw,out,cover=self.fixture(Path(folder));plan=plan_cleanup([b.folder], 'originals')
            with patch.object(RecreationBatch,'save',side_effect=OSError('read only')):
                result=execute_cleanup(plan,w)
            self.assertTrue(result['errors']); self.assertFalse(raw.exists())
            self.assertEqual(len(w.inputs['md5']),1)
            self.assertEqual(len(w.resolve_inputs('md5')),1)
            self.assertTrue(out.exists())

    def test_external_symlink_target_is_protected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);w,b,raw,out,cover=self.fixture(root)
            outside=root/'important.mp4';outside.write_bytes(b'keep')
            link=out.with_name('linked.mp4')
            try:link.symlink_to(outside)
            except OSError:self.skipTest('Symlink creation not permitted')
            b.add_outputs([{'path':str(link),'drama':'test','mode':'md5','metadata':{}}])
            result=execute_cleanup(plan_cleanup([b.folder], 'products'),w)
            self.assertTrue(outside.exists());self.assertTrue(link.exists())
            self.assertEqual(result['protected'],1)
