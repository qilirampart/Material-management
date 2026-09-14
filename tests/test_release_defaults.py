import json
import unittest
from pathlib import Path

from src.desktop import default_material_output_root, with_runtime_config_defaults


class ReleaseDefaultTests(unittest.TestCase):
    def test_bundled_example_never_contains_a_developer_machine_path(self):
        root = Path(__file__).resolve().parents[1]
        config = json.loads((root / "config.example.json").read_text(encoding="utf-8"))
        for key in ("model_config_path", "parser_config_path", "downloader_config_path"):
            self.assertEqual(config[key], "")

    def test_missing_paths_default_to_the_current_users_runtime_folder(self):
        config = with_runtime_config_defaults({}, "C:/Users/Alice/AppData/Local/Dianzhong/MaterialAssistant/runtime", "D:/AliceData")
        self.assertEqual(Path(config["output_root"]), Path("D:/AliceData/output"))
        self.assertEqual(Path(config["model_config_path"]), Path("C:/Users/Alice/AppData/Local/Dianzhong/MaterialAssistant/runtime/model_profiles.json"))
        self.assertEqual(Path(config["parser_config_path"]), Path("C:/Users/Alice/AppData/Local/Dianzhong/MaterialAssistant/runtime/api_config.json"))
        self.assertEqual(Path(config["downloader_config_path"]), Path("C:/Users/Alice/AppData/Local/Dianzhong/MaterialAssistant/runtime/downloader_config.json"))

    def test_first_run_prefers_dianzhong_folder_on_d_drive(self):
        self.assertEqual(default_material_output_root(d_drive_available=True), Path("D:/DianZhong"))
        self.assertEqual(default_material_output_root(d_drive_available=False), Path("C:/DianZhong"))

    def test_previous_developer_defaults_are_replaced_for_existing_users(self):
        config = with_runtime_config_defaults(
            {"parser_config_path": "E:\\点众\\自动化工具\\侵权巡检助手工作区\\源码\\runtime\\api_config.json"},
            "C:/Users/Alice/AppData/Local/Dianzhong/MaterialAssistant/runtime",
        )
        self.assertEqual(
            Path(config["parser_config_path"]),
            Path("C:/Users/Alice/AppData/Local/Dianzhong/MaterialAssistant/runtime/api_config.json"),
        )
