import unittest
from src.download_progress import DownloadProgress


class ProgressTests(unittest.TestCase):
    def test_throttle_completion_and_retry(self):
        now = [0.0]
        events = []
        progress = DownloadProgress(events.append, lambda: now[0])
        progress(0, 100)
        now[0] = .1
        progress(10, 100)
        self.assertEqual(len(events), 1)
        now[0] = .5
        progress(50, 100)
        self.assertEqual(events[-1]['percent'], 50)
        self.assertEqual(events[-1]['speed'], 100)
        progress(100, 100)
        self.assertEqual(events[-1]['percent'], 100)
        progress(0, 200)
        self.assertEqual(events[-1]['percent'], 0)
        self.assertEqual(events[-1]['speed'], 0)

    def test_unknown_size_does_not_invent_percent(self):
        events = []
        progress = DownloadProgress(events.append, lambda: 0)
        progress(0, 0)
        self.assertIsNone(events[-1]['percent'])
