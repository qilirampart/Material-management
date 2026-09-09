import json
import unittest

from src.platform_bridge import (
    build_json_result_script,
    build_read_upload_selection_script,
    build_upload_file_input_script,
    build_upload_form_script,
    parse_json_result,
)


class PlatformBridgeTests(unittest.TestCase):
    def test_qt_browser_result_is_json_serialized_and_parsed(self):
        script = "(() => ({ok:true, code:'READY'}))()"

        self.assertEqual(build_json_result_script(script), f"JSON.stringify({script})")
        self.assertEqual(parse_json_result('{"ok":true,"code":"READY"}'), {"ok": True, "code": "READY"})
        self.assertEqual(parse_json_result(""), {})

    def test_read_script_extracts_platform_director_and_drama_selection(self):
        script = build_read_upload_selection_script()

        self.assertIn("directorSelect", script)
        self.assertIn("bookIdSelect", script)
        self.assertIn("selectedOptions", script)
        self.assertNotIn("click()", script)

    def test_file_input_script_targets_upload_form_without_submitting(self):
        script = build_upload_file_input_script()

        self.assertIn("uploadVideoFile", script)
        self.assertIn("material_add", script)
        self.assertNotIn("click()", script)

    def test_script_contains_upload_fields_without_draft_or_review_actions(self):
        script = build_upload_form_script(
            director="王俨",
            drama_name="婚房门后的秘密",
            drama_platform_id="98765",
            file_count=2,
        )

        self.assertIn("uploadVideoFile", script)
        self.assertIn("sponsorSelect", script)
        self.assertIn("deptSelect", script)
        self.assertIn("bookIdSelect", script)
        self.assertIn("BOOK_SEARCH_STARTED", script)
        self.assertIn("SOURCE_TYPE_CHANGING", script)
        self.assertIn("xm-select-input", script)
        self.assertIn("onChangeAdTargetType", script)
        self.assertNotIn("#ensure", script)
        self.assertNotIn("提交审核", script)
        self.assertNotIn("保存草稿", script)

    def test_dynamic_values_are_serialized_as_json_data(self):
        drama = '剧名"\\换行\n测试'
        script = build_upload_form_script(
            director="编导'测试",
            drama_name=drama,
            drama_platform_id="12",
            file_count=1,
        )

        self.assertIn(json.dumps(drama, ensure_ascii=False), script)
        self.assertIn(json.dumps("编导'测试", ensure_ascii=False), script)


if __name__ == "__main__":
    unittest.main()
