import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from src.recreation import RecreationBatch
from src.recreation_platform import collect_platform_materials,download_platform_materials,build_platform_job_script


class MaterialNameFilterTests(unittest.TestCase):
    def test_query_sends_observed_exclusion_and_locally_rejects_square_name_but_keeps_landscape(self):
        class Client:
            def __init__(self):self.filters=[]
            def lookup(self,drama):return {'id':drama['id'],'name':'测试剧'}
            def fetch_page(self,drama,keyword,page,start,end,*,exclude_name=''):
                self.filters.append(exclude_name)
                return {'items':[{'id':'1','name':'二创【小方块】'},{'id':'2','name':'精剪原片-横版'}],
                    'has_next':False,'total':2}
        with tempfile.TemporaryDirectory() as folder:
            batch=RecreationBatch.create(folder,[{'id':'4100','name':'测试剧'}]);client=Client()
            result=collect_platform_materials(batch,client,'2014-01-01','2026-11-15',exclude_name='小方块')
            self.assertEqual(client.filters,['小方块','小方块'])
            self.assertEqual([x['name'] for x in batch.state['sources']],['精剪原片-横版'])
            self.assertEqual(RecreationBatch.load(batch.folder).state['exclude_name'],'小方块')
            self.assertEqual(result['count'],1)
        script=build_platform_job_script('job','list',{'exclude_name':'小方块'})
        self.assertIn('excludeMaterialName',script)

    def test_download_guard_applies_to_existing_batch_and_never_calls_source_or_transfer(self):
        with tempfile.TemporaryDirectory() as folder:
            batch=RecreationBatch.create(folder,[{'id':'4100','name':'测试剧'}])
            batch.record_page(batch.state['dramas'][0],[{'id':'1','name':'二创-小方块'}],1)
            batch.state['exclude_name']='小方块';batch.save()
            with patch('src.recreation_platform.download_material') as transfer:
                result=download_platform_materials(batch,object())
            transfer.assert_not_called();self.assertEqual(result['excluded'],1);self.assertEqual(result['failed'],0)
            self.assertEqual(batch.state['sources'][0]['download_status'],'pending')
            self.assertEqual(len(batch.state['sources']),1)

    def test_old_batches_without_filter_keep_their_original_download_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            batch=RecreationBatch.create(folder,[{'id':'4100','name':'测试剧'}])
            self.assertEqual(batch.state.get('exclude_name',''),'')
