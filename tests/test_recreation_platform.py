import tempfile
import unittest
import requests
from pathlib import Path
from unittest.mock import patch

from src.recreation import RecreationBatch, RecreationStopped
from src.recreation_platform import (
    build_platform_job_script, collect_platform_materials, download_platform_materials, download_material,
    parse_material_page, validate_material_url,
    PlatformMaterialClient, PlatformRateLimited,
)
from src.media import run


class RecreationPlatformTests(unittest.TestCase):
    def test_download_retries_connection_failure_and_replaces_partial_bytes(self):
        class Response:
            status_code = 200
            headers = {'content-length': '4'}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def iter_content(self, size): yield b'done'
        with tempfile.TemporaryDirectory() as folder:
            partial = Path(folder) / 'video.mp4.part'
            partial.write_bytes(b'old partial bytes')
            with patch('src.recreation_platform.requests.get', side_effect=[requests.ConnectionError('private URL'), Response()]) as get, \
                    patch('src.recreation_platform.time.sleep'):
                download_material('https://material.wuread.cn/video', partial)
            self.assertEqual(get.call_count, 2)
            self.assertEqual(partial.read_bytes(), b'done')

    def test_stop_during_retry_does_not_issue_another_request(self):
        stopped = []
        with tempfile.TemporaryDirectory() as folder, \
                patch('src.recreation_platform.requests.get', side_effect=requests.Timeout('private URL')) as get, \
                patch('src.recreation_platform.time.sleep', side_effect=lambda _: stopped.append(True)):
            with self.assertRaises(RecreationStopped):
                download_material('https://material.wuread.cn/video', Path(folder) / 'video.part',
                                  should_stop=lambda: bool(stopped))
            self.assertEqual(get.call_count, 1)

    def test_permanent_http_failure_is_not_retried_and_does_not_overwrite_partial(self):
        class Response:
            status_code = 403
            def __enter__(self): return self
            def __exit__(self, *args): pass
        with tempfile.TemporaryDirectory() as folder:
            partial = Path(folder) / 'video.part'
            partial.write_bytes(b'previous attempt')
            with patch('src.recreation_platform.requests.get', return_value=Response()) as get:
                with self.assertRaisesRegex(RuntimeError, 'HTTP 403'):
                    download_material('https://material.wuread.cn/video', partial)
                self.assertEqual(get.call_count, 1)
            self.assertEqual(partial.read_bytes(), b'previous attempt')

    def test_retry_exhaustion_is_bounded_and_does_not_disclose_url(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch('src.recreation_platform.requests.get', side_effect=requests.Timeout('secret signed URL')) as get, \
                patch('src.recreation_platform.time.monotonic', side_effect=range(0, 1000, 20)):
            with self.assertRaisesRegex(RuntimeError, '3 次') as raised:
                download_material('https://material.wuread.cn/video', Path(folder) / 'video.part')
            self.assertNotIn('secret', str(raised.exception))
            self.assertEqual(get.call_count, 3)

    def test_changing_dates_requires_new_batch_instead_of_mixing_query_results(self):
        with tempfile.TemporaryDirectory() as folder:
            batch = RecreationBatch.create(folder, [{'id': '4100', 'name': '测试剧'}])
            batch.record_page(batch.state['dramas'][0], [{'id': '1', 'name': '二创'}], 1)
            batch.state['query_dates'] = {'start': '2014-01-01', 'end': '2026-11-12'}
            with self.assertRaisesRegex(ValueError, '新建批次'):
                collect_platform_materials(batch, object(), '2026-11-01', '2026-11-12')
            self.assertEqual(batch.state['query_dates']['start'], '2014-01-01')

    def test_rate_limit_is_retried_with_wait_not_immediate_repeated_requests(self):
        client = PlatformMaterialClient('ws://test')
        with patch.object(client, '_request_once', side_effect=[PlatformRateLimited(5), {'id':'4100'}]) as request, \
                patch.object(client, '_wait') as wait:
            self.assertEqual(client.lookup({'id':'4100'}), {'id':'4100'})
            self.assertEqual(request.call_count, 2)
            self.assertIn(5, [call.args[0] for call in wait.call_args_list])
    def test_page_checks_query_identity_and_explicit_total(self):
        payload = {'total': '101', 'rows': [{'id': str(i), 'name': '二创', 'book_id': '4100'} for i in range(100)]}
        result = parse_material_page(payload, '4100', 1, 100)
        self.assertTrue(result['has_next'])
        for invalid in ({'rows': []}, {'total': 1, 'rows': [{'id': '1', 'name': '二创', 'book_id': '4200'}]}):
            with self.assertRaises(ValueError):
                parse_material_page(invalid, '4100', 1, 100)

    def test_short_or_duplicate_page_cannot_silently_skip_materials(self):
        row = {'id': '1', 'name': '二创', 'book_id': '4100'}
        for payload in ({'total': 101, 'rows': [row]},
                        {'total': 2, 'rows': [row, row]}):
            with self.assertRaises(ValueError):
                parse_material_page(payload, '4100', 1)

    def test_recover_existing_video_without_requesting_expired_platform_url(self):
        with tempfile.TemporaryDirectory() as folder:
            batch = RecreationBatch.create(folder, [{'id': '4100', 'name': '测试剧'}])
            batch.record_page(batch.state['dramas'][0], [{'id': '1', 'name': '二创'}], 1)
            item = batch.state['sources'][0]
            target = batch.download_target(item)
            target.parent.mkdir(parents=True)
            target.write_bytes(b'existing validated video')
            with patch('src.recreation_platform.validate_video', return_value={'duration': 1}), \
                    patch('src.recreation_platform.download_material') as transfer:
                result = download_platform_materials(batch, object())
            self.assertEqual(result['completed'], 1)
            transfer.assert_not_called()
            self.assertEqual(RecreationBatch.load(batch.folder).state['sources'][0]['path'], str(target.resolve()))

    def test_reload_recovers_interrupted_query_but_read_only_snapshot_does_not(self):
        with tempfile.TemporaryDirectory() as folder:
            batch = RecreationBatch.create(folder, [{'id': '4100', 'name': '测试剧'}])
            batch.state['collection_status'] = 'in_progress'
            batch.save()
            self.assertEqual(RecreationBatch.load(batch.folder, recover_interrupted=False).state['collection_status'], 'in_progress')
            self.assertEqual(RecreationBatch.load(batch.folder).state['collection_status'], 'paused')

    def test_scripts_only_use_observed_read_endpoints_and_do_not_export_credentials(self):
        script = build_platform_job_script('job1', 'list', {
            'drama_id': '4100', 'keyword': '二创', 'page': 1,
            'start_date': '2014-01-01', 'end_date': '2026-11-12',
        })
        self.assertIn('/material/material/cardList', script)
        self.assertIn('uploadTimeBegin', script)
        self.assertNotIn('localStorage', script)
        self.assertNotIn('document.cookie', script)
        self.assertNotIn('window.open', script)

    def test_signed_material_url_is_preserved_but_arbitrary_targets_are_rejected(self):
        url = 'https://material.wuread.cn/path/video.mp4?signature=sample'
        self.assertEqual(validate_material_url(url), url)
        for url in ('http://127.0.0.1/video', 'https://evil.test/video',
                    'https://user:pass@material.wuread.cn/video'):
            with self.assertRaises(ValueError):
                validate_material_url(url)

    def test_collects_both_keywords_and_persists_union_without_changing_other_batch(self):
        class Client:
            def lookup(self, drama): return {'id': drama['id'], 'name': '测试剧'}
            def fetch_page(self, drama, keyword, page, start_date, end_date):
                return {'items': [{'id': '1', 'name': '二创'}, {'id': '2', 'name': '精剪原片'}],
                        'has_next': False, 'total': 2}

        with tempfile.TemporaryDirectory() as folder:
            batch = RecreationBatch.create(folder, [{'id': '4100', 'name': ''}])
            other = RecreationBatch.create(folder, [{'id': '4200', 'name': ''}])
            collect_platform_materials(batch, Client(), '2014-01-01', '2026-11-12')
            self.assertEqual(len(batch.state['sources']), 2)
            self.assertEqual(batch.state['collection_status'], 'complete')
            self.assertEqual(batch.state['dramas'][0]['name'], '测试剧')
            self.assertEqual(other.state['sources'], [])

    def test_download_validates_each_file_and_skips_successful_files_on_retry(self):
        class Client:
            def source_url(self, material_id): return 'https://material.wuread.cn/' + material_id

        with tempfile.TemporaryDirectory() as folder:
            batch = RecreationBatch.create(folder, [{'id': '4100', 'name': '测试剧'}])
            batch.record_page(batch.state['dramas'][0], [{'id': '1', 'name': '二创'}], 1)
            calls = []
            def transfer(url, partial, **kwargs):
                calls.append(url)
                run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i',
                     'testsrc2=size=160x240:rate=15:duration=1', '-c:v', 'libx264',
                     '-f', 'mp4', str(partial)])
            download_platform_materials(batch, Client(), transfer=transfer)
            self.assertEqual(batch.state['sources'][0]['download_status'], 'downloaded')
            download_platform_materials(batch, Client(), transfer=transfer)
            self.assertEqual(len(calls), 1)

    def test_cancelled_download_does_not_start_next_and_preserves_pending_state(self):
        class Client:
            def source_url(self, material_id): return 'https://material.wuread.cn/' + material_id
        with tempfile.TemporaryDirectory() as folder:
            batch = RecreationBatch.create(folder, [{'id': '4100', 'name': '测试剧'}])
            batch.record_page(batch.state['dramas'][0], [{'id': '1', 'name': '二创'},
                             {'id': '2', 'name': '二创'}], 1)
            with patch('src.recreation_platform.download_material', side_effect=RecreationStopped('stop')) as transfer:
                result = download_platform_materials(batch, Client())
                self.assertTrue(result['stopped'])
                self.assertEqual(transfer.call_count, 1)
                self.assertTrue(all(x['download_status'] == 'pending' for x in batch.state['sources']))
