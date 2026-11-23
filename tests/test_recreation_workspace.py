import tempfile
import unittest
from pathlib import Path
from src.recreation_workspace import RecreationWorkspace


class WorkspaceTests(unittest.TestCase):
    def test_multi_drama_excel_keeps_downloads_and_products_in_their_drama_folders(self):
        from openpyxl import Workbook
        from shutil import copyfile
        from src.material_variants import VariantOptions, generate_variants
        from src.media import run
        from src.recreation_platform import download_platform_materials
        from unittest.mock import Mock

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = RecreationWorkspace(root/'prefs.json', root)
            book = Workbook()
            book.active.append(['剧目ID', '剧名'])
            dramas = [('4100','第一剧'), ('4200','第二剧')]
            for identity, title in dramas:
                book.active.append([identity, title])
            sheet = root/'多剧清单.xlsx'
            book.save(sheet)
            clip = root/'sample.mp4'
            run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=size=160x240:rate=15:duration=1',
                 '-c:v','libx264',str(clip)])
            batches = store.import_files([sheet])
            self.assertEqual(len(batches), 2)
            for batch, (identity, title) in zip(batches, dramas):
                drama = batch.state['dramas'][0]
                self.assertEqual((drama['id'], drama['name']), (identity, title))
                batch.record_page(drama, [{'id':'55','name':'素材'}], 1)
                result = download_platform_materials(batch, Mock(),
                    transfer=lambda url, path, **kw: copyfile(clip, path))
                self.assertEqual(result['remaining_ids'], [])
                item = batch.state['sources'][0]
                self.assertEqual(Path(item['path']), batch.folder/title/'原始素材'/'55.mp4')
                report = generate_variants([item], batch.folder/'加工成品', VariantOptions(mode='md5'))
                product = report['outputs'][0]
                self.assertEqual(product['source_video_id'], f'{identity}_55')
                self.assertEqual(Path(product['path']).parent.parent.name, title)
                self.assertTrue(Path(product['path']).is_relative_to(batch.folder/'加工成品'))

    def test_csv_drama_list_and_invalid_excel_have_explicit_results(self):
        with tempfile.TemporaryDirectory() as folder:
            store = RecreationWorkspace(Path(folder) / 'prefs.json', folder)
            csv = Path(folder) / 'dramas.csv'
            csv.write_text('剧目ID,剧名\n4100,第一剧\n4200,第二剧\n', encoding='utf-8-sig')
            batches = store.import_files([csv])
            self.assertEqual([b.state['dramas'][0]['id'] for b in batches], ['4100', '4200'])
            invalid = Path(folder) / 'invalid.xlsx'
            invalid.write_bytes(b'not an excel workbook')
            with self.assertRaisesRegex(ValueError, 'Excel 文件无效'):
                store.import_files([invalid])
    def test_invalid_last_batch_does_not_crash_new_workspace(self):
        with tempfile.TemporaryDirectory() as folder:
            from src.batch import save_json
            path = Path(folder) / 'prefs.json'
            save_json(path, {'last_batch': 42})
            store = RecreationWorkspace(path, folder)
            self.assertEqual(store.last_batch, '')
            self.assertTrue(store.load_error)
    def test_separate_batches_durable_queue_and_processing_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            store = RecreationWorkspace(Path(folder) / 'workspace.json', folder)
            batches = store.create('4100-第一剧\n4200-第二剧')
            self.assertEqual(len(batches), 2)
            self.assertEqual([len(b.state['dramas']) for b in batches], [1, 1])
            first = batches[0]
            first.record_page(first.state['dramas'][0], [{'id': '1', 'name': '二创'}], 1)
            store.enqueue(first.folder, ['4100_1'])
            store.add_inputs('md5', first.folder, ['4100_1'])
            store.add_inputs('md5', first.folder, ['4100_1'])
            restored = RecreationWorkspace(store.path, folder)
            self.assertEqual(len(restored.folders), 2)
            self.assertEqual(len(restored.queue), 1)
            self.assertEqual(len(restored.inputs['md5']), 1)
            self.assertEqual(restored.inputs['micro'], [])
            self.assertFalse(restored.queue_running)

    def test_old_last_batch_preference_remains_usable(self):
        with tempfile.TemporaryDirectory() as folder:
            from src.recreation import RecreationBatch
            from src.batch import save_json
            batch = RecreationBatch.create(folder, [{'id': '4100', 'name': '测试剧'}])
            path = Path(folder) / 'prefs.json'
            save_json(path, {'last_batch': str(batch.folder)})
            store = RecreationWorkspace(path, folder)
            self.assertEqual(store.folders, [str(batch.folder)])

    def test_imports_drama_spreadsheet_filename_without_reading_user_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            store = RecreationWorkspace(Path(folder) / 'prefs.json', folder)
            batches = store.import_files([Path(folder) / '4100-测试剧.xlsx'])
            self.assertEqual(batches[0].state['dramas'], [{'id': '4100', 'name': '测试剧'}])
