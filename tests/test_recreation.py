import tempfile
import unittest
from pathlib import Path

from src.recreation import RecreationBatch, collect_all_pages, parse_dramas
from src.media import run


class RecreationTests(unittest.TestCase):
    def test_download_is_only_complete_after_video_validation_and_is_grouped_by_drama(self):
        with tempfile.TemporaryDirectory() as folder:
            batch = RecreationBatch.create(folder, [{'id': '4100', 'name': '测试剧'}])
            batch.record_page(batch.state['dramas'][0], [{'id': '123', 'name': '二创素材'}], 1)
            partial = batch.begin_download('4100_123')
            self.assertEqual(batch.state['sources'][0]['download_status'], 'downloading')
            run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i',
                 'testsrc2=size=160x240:rate=15:duration=1', '-c:v', 'libx264',
                 '-f', 'mp4', str(partial)])
            batch.complete_download('4100_123')
            restored = RecreationBatch.load(batch.folder)
            item = restored.state['sources'][0]
            self.assertEqual(item['download_status'], 'downloaded')
            self.assertEqual(Path(item['path']).parent.name, '原始素材')
            self.assertEqual(Path(item['path']).parent.parent.name, '测试剧')
            self.assertFalse(partial.exists())

    def test_interrupted_download_is_recoverable_not_marked_finished(self):
        with tempfile.TemporaryDirectory() as folder:
            batch = RecreationBatch.create(folder, [{'id': '4100', 'name': '测试剧'}])
            batch.record_page(batch.state['dramas'][0], [{'id': '123', 'name': '二创素材'}], 1)
            partial = batch.begin_download('4100_123')
            partial.write_bytes(b'incomplete')
            restored = RecreationBatch.load(batch.folder)
            self.assertEqual(restored.state['sources'][0]['download_status'], 'pending')
            self.assertEqual(restored.state['sources'][0]['path'], '')
            self.assertTrue(partial.is_file())

    def test_drama_input_is_deduplicated_without_losing_name(self):
        self.assertEqual(parse_dramas('4100-测试剧\n4200\n4100-测试剧'), [
            {'id': '4100', 'name': '测试剧'}, {'id': '4200', 'name': ''},
        ])
        with self.assertRaises(ValueError):
            parse_dramas('无 ID 的剧名')

    def test_punctuation_inside_drama_name_is_preserved(self):
        self.assertEqual(parse_dramas('41000321637-嫁厂长，八零福星旺全家'), [
            {'id': '41000321637', 'name': '嫁厂长，八零福星旺全家'},
        ])

    def test_collects_both_keywords_all_pages_and_deduplicates(self):
        calls = []

        def fetch(drama, page):
            calls.append(page)
            records = [
                {'id': '1', 'name': '二创素材', 'url': 'https://example.org/1'},
                {'id': str(page + 1), 'name': '精剪原片素材', 'url': 'https://example.org/2'},
                {'id': 'x', 'name': '其他素材', 'url': 'https://example.org/x'},
            ]
            return {'items': records, 'has_next': page < 2}

        result = collect_all_pages({'id': '4100', 'name': '测试剧'}, fetch)
        self.assertEqual(calls, [1, 2])
        self.assertEqual([x['id'] for x in result], ['1', '2', '3'])

    def test_repeated_page_and_unknown_pagination_never_claim_complete(self):
        for fetch in (
            lambda drama, page: {'items': [{'id': '1', 'name': '二创'}], 'has_next': True},
            lambda drama, page: {'items': []},
        ):
            with self.assertRaises(ValueError):
                collect_all_pages({'id': '4100', 'name': ''}, fetch)

    def test_batches_keep_sources_and_outputs_separate_and_restore(self):
        with tempfile.TemporaryDirectory() as folder:
            one = RecreationBatch.create(folder, [{'id': '4100', 'name': '测试剧'}])
            two = RecreationBatch.create(folder, [{'id': '4200', 'name': '第二剧'}])
            source = Path(folder) / '原视频.mp4'
            source.write_bytes(b'video')
            one.add_local_sources([str(source)], {'id': '4100', 'name': '测试剧'})
            one.add_local_sources([str(source)], {'id': '4100', 'name': '测试剧'})
            self.assertEqual(len(one.state['sources']), 1)
            self.assertEqual(two.state['sources'], [])
            restored = RecreationBatch.load(one.folder)
            self.assertEqual(restored.state['sources'], one.state['sources'])
            self.assertIn('再创作', str(one.folder))
            self.assertTrue(source.is_file())
