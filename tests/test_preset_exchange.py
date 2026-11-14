import json
import tempfile
import unittest
from pathlib import Path
from copy import deepcopy
from src.micro_presets import RECOMMENDED,read_preset_package,export_preset_package,merge_imported_presets


class PresetExchangeTests(unittest.TestCase):
    def test_current_settings_round_trip_without_credentials_or_batch_state(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'format.json';values=deepcopy(RECOMMENDED)
            values.update(grid_layout='quad',picture_style='sepia',cover_mode='image',cover_path='D:/missing/cover.png')
            export_preset_package(path,'四宫格',values)
            data=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(set(data),{'format','schema','presets'})
            self.assertEqual(read_preset_package(path),{'四宫格':values})
            self.assertNotIn('uploader',data['presets']['四宫格'])
            with self.assertRaises(ValueError):export_preset_package(path,'非法',dict(values,api_key='secret'))
            self.assertEqual(read_preset_package(path),{'四宫格':values})

    def test_collision_keep_both_is_deterministic_and_does_not_mutate_inputs(self):
        local={'风格':deepcopy(RECOMMENDED),'风格（导入）':deepcopy(RECOMMENDED)}
        incoming={'风格':dict(RECOMMENDED,speed=1.1),'新风格':dict(RECOMMENDED,speed=.9)}
        before=deepcopy(local)
        merged,names=merge_imported_presets(local,incoming,replace_existing=False)
        self.assertEqual(local,before);self.assertEqual(names,['风格（导入2）','新风格'])
        self.assertEqual(merged['风格']['speed'],RECOMMENDED['speed'])
        self.assertEqual(merged['风格（导入2）']['speed'],1.1)
        incoming['风格']['speed']=1
        self.assertEqual(merged['风格（导入2）']['speed'],1.1)
        replaced,names=merge_imported_presets(local,{'风格':dict(RECOMMENDED,speed=1.15)},replace_existing=True)
        self.assertEqual(replaced['风格']['speed'],1.15);self.assertEqual(names,['风格'])

    def test_rejects_wrong_format_partial_invalid_package_and_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'import.json'
            valid={'format':'dianzhong.micro-presets','schema':1,'presets':{'可用':RECOMMENDED}}
            for data in (dict(valid,format='cvp'),dict(valid,schema=99),dict(valid,presets={}),
                    dict(valid,presets={'可用':RECOMMENDED,'坏':dict(RECOMMENDED,speed=9)})):
                path.write_text(json.dumps(data),encoding='utf-8')
                with self.assertRaises(ValueError):read_preset_package(path)
            path.write_text('{"schema":1,"schema":2}',encoding='utf-8')
            with self.assertRaises(ValueError):read_preset_package(path)

    def test_old_parameters_migrate_and_long_names_stay_within_limit(self):
        name='长'*40
        merged,names=merge_imported_presets({name:RECOMMENDED},{name:RECOMMENDED},replace_existing=False)
        self.assertLessEqual(len(names[0]),40);self.assertEqual(len(merged),2)

    def test_shared_recipes_reject_network_paths_before_any_resource_lookup(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for path in ('\\\\server\\share\\music.mp3','//server/share/image.png','https://example.com/file.png'):
                with self.assertRaises(ValueError):export_preset_package(root/'shared.json','远程引用',dict(RECOMMENDED,music_path=path))
            values=dict(RECOMMENDED,resource_pools={'background_path':'\\\\server\\share'})
            with self.assertRaises(ValueError):export_preset_package(root/'shared.json','远程资源池',values)
            payload={'format':'dianzhong.micro-presets','schema':1,'presets':{'网络引用':values}}
            (root/'malicious.json').write_text(json.dumps(payload),encoding='utf-8')
            with self.assertRaises(ValueError):read_preset_package(root/'malicious.json')
