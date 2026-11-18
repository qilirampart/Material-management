import json
import shutil
import subprocess
import unittest
from unittest.mock import patch
from src.recreation_platform import material_ready_script, PlatformMaterialClient


@unittest.skipUnless(shutil.which('node'), 'Node is needed for JavaScript fixture execution')
class MaterialReadinessTests(unittest.TestCase):
    def evaluate(self, setup, open_page=True):
        code = "const vm=require('node:vm');let clicks=0;" + """
        function make(path,frames=[],ready=false) {
          return {location:{pathname:path}, Material:ready?{}:undefined,$ax:ready?{}:undefined,
            document:{querySelectorAll(kind){return kind==='iframe'?frames:
              [{getAttribute(){return '/market-admin/material/material'},click(){clicks++}}]}}};
        }
        """ + setup + ';console.log(JSON.stringify({result:vm.runInNewContext(' + json.dumps(material_ready_script(open_page)) + ',{window:root,document:root.document,location:root.location}),get clicks(){return clicks}}));'
        result = subprocess.run(['node', '-e', code], capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def test_direct_material_page_is_ready(self):
        self.assertEqual(self.evaluate("const root=make('/market-admin/material/material',[],true)")['result']['status'],'ready')

    def test_nested_material_frame_and_unrelated_inaccessible_frame(self):
        result=self.evaluate("const bad={get contentWindow(){throw Error('cross-origin')}}; const child=make('/market-admin/material/material/',[],true); const root=make('/market-admin/',[bad,{contentWindow:make('/shell',[{contentWindow:child}])}])")
        self.assertEqual(result['result']['status'],'ready');self.assertEqual(result['clicks'],0)

    def test_not_ready_opens_menu_once_not_on_every_poll(self):
        setup="const root=make('/market-admin/',[{contentWindow:make('/market-admin/material/material')}])"
        self.assertEqual(self.evaluate(setup)['clicks'],1)
        self.assertEqual(self.evaluate(setup,False)['clicks'],0)

    def test_login_is_not_reported_as_empty_search(self):
        self.assertEqual(self.evaluate("const root=make('/market-admin/login')")['result']['status'],'login')

    def test_waits_for_late_menu_then_clicks_only_once(self):
        with patch('src.recreation_platform.evaluate_edge_page', side_effect=[
                {'status':'opening'}, {'status':'opening','opened':True}, {'status':'ready'}]), \
                patch('src.recreation_platform.material_ready_script', wraps=material_ready_script) as script, \
                patch('src.recreation_platform.time.sleep'):
            PlatformMaterialClient('ws://fixture').ensure_ready()
        self.assertEqual([c.args[0] for c in script.call_args_list], [True,True,False])
