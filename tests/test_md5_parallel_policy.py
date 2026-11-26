import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from src.md5_parallel import choose_lanes, limited_work


class Md5ParallelPolicyTests(unittest.TestCase):
    def test_prompts_only_when_requested_and_a_download_is_active(self):
        self.assertEqual(choose_lanes(2,False,True), (2,''))
        self.assertEqual(choose_lanes(2,True,True), (2,'download'))
        self.assertEqual(choose_lanes(2,True,False), (1,'unsupported'))
        self.assertEqual(choose_lanes(1,True,True), (1,''))

    def test_single_slot_does_not_start_another_item_until_current_finishes(self):
        seen=[]
        def work(v):
            seen.append(v)
            return v
        self.assertEqual(list(limited_work(range(4),work,lambda:1,lambda:False)), [0,1,2,3])
        self.assertEqual(seen,[0,1,2,3])

    def test_new_work_is_throttled_then_resumes_dual_without_interrupting_active_work(self):
        started = [Event() for _ in range(5)]
        done = [Event() for _ in started]
        download = Event()

        def work(index):
            started[index].set()
            if not done[index].wait(5):
                raise TimeoutError(index)
            return index

        def run():
            return list(limited_work(range(5), work, lambda: 1 if download.is_set() else 2, lambda: False))

        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(run)
            try:
                self.assertTrue(started[0].wait(3))
                self.assertTrue(started[1].wait(3))
                download.set()
                done[0].set()
                self.assertFalse(started[2].wait(.3))
                done[1].set()
                self.assertTrue(started[2].wait(3))
                self.assertFalse(started[3].wait(.3))
                download.clear()
                self.assertTrue(started[3].wait(3))
                self.assertFalse(started[4].is_set())
            finally:
                for event in done:
                    event.set()
            self.assertCountEqual(result.result(3), range(5))
