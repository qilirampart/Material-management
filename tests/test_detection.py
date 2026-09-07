import unittest

from src.vision import classify


def frame(index, text="", logo="absent", uncertain=False):
    return {"index": index, "text": text, "logo": logo,
            "logo_evidence": "右上角图标" if logo == "present" else "",
            "uncertain": uncertain}


class DetectionTests(unittest.TestCase):
    def test_each_requested_phrase_blocks(self):
        for phrase in ["0元免费看", "免费观看", "免 费\n看", "一分钱不花", "一分錢不花"]:
            with self.subTest(phrase=phrase):
                result = classify({"frames": [frame(1, phrase), frame(2), frame(3)]})
                self.assertEqual(result["status"], "blocked")

    def test_logo_with_evidence_blocks(self):
        self.assertEqual(classify({"frames": [frame(1, logo="present"), frame(2), frame(3)]})["status"], "blocked")

    def test_missing_frames_never_clear(self):
        self.assertEqual(classify({"frames": [frame(1)]})["status"], "review_required")

    def test_duplicate_indices_never_clear(self):
        self.assertEqual(classify({"frames": [frame(1), frame(1), frame(3)]})["status"], "review_required")

    def test_ambiguous_logo_never_clear(self):
        self.assertEqual(classify({"frames": [frame(1, logo="uncertain"), frame(2), frame(3)]})["status"], "review_required")

    def test_string_false_is_invalid(self):
        invalid = frame(1)
        invalid["uncertain"] = "false"
        self.assertEqual(classify({"frames": [invalid, frame(2), frame(3)]})["status"], "review_required")

    def test_free_alone_does_not_block(self):
        self.assertEqual(classify({"frames": [frame(1, "免费停车"), frame(2), frame(3)]})["status"], "sample_clear")

    def test_explicit_hit_still_blocks_if_another_frame_missing(self):
        self.assertEqual(classify({"frames": [frame(1, "免费看")]})["status"], "blocked")
