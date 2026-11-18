"""Install into an isolated obsolete-runtime fixture, then run the installed app.

Compile installer.iss with /DUpgradeTestBuild: no shortcuts/uninstall registry
are changed. Only temporary files created by this script are removed.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def verify(installer, evidence):
    installer=Path(installer).resolve()
    evidence=Path(evidence).resolve(); evidence.mkdir(parents=True,exist_ok=True)
    if os.name != 'nt':
        raise RuntimeError('This installed upgrade check requires Windows')
    with tempfile.TemporaryDirectory(prefix='upgrade-check-',dir=evidence) as temporary:
        root=Path(temporary).resolve(); app=root/'app'; internal=app/'_internal'
        assert app.is_relative_to(root) and root.is_relative_to(evidence)
        for name in ('numpy/_core/legacy.pyd','numpy.libs/legacy.dll','obsolete-runtime-file.pyd'):
            path=internal/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'obsolete')
        preserved_user_files={}
        for name in ('runtime/desktop_config.json','runtime/recreation-workspace.json',
                     'output/素材再创作/old-batch/recreation.json','output/videos/keep.mp4'):
            path=app/name;path.parent.mkdir(parents=True,exist_ok=True)
            content=b'user-data-must-survive';path.write_bytes(content)
            preserved_user_files[name]=content
        flags={'creationflags':subprocess.CREATE_NO_WINDOW}
        subprocess.run([str(installer),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',
            '/NOICONS','/TASKS=',f'/DIR={app}',f'/LOG={evidence/"install.log"}'],
            check=True,timeout=240,**flags)
        for name in ('numpy','numpy.libs','obsolete-runtime-file.pyd'):
            if (internal/name).exists():
                raise RuntimeError('Obsolete dependency survived upgrade: '+name)
        for name,content in preserved_user_files.items():
            if (app/name).read_bytes()!=content:
                raise RuntimeError('User data changed during upgrade: '+name)
        profile=root/'isolated-profile';(profile/'runtime').mkdir(parents=True)
        (profile/'materials').mkdir()
        config={'output_root':str(profile/'materials'),'internal_browser_debug_port':9248,
                'platform_browser_data_path':str(profile/'browser')}
        (profile/'runtime/desktop_config.json').write_text(json.dumps(config),encoding='utf-8')
        env={**os.environ,'QT_QPA_PLATFORM':'offscreen','MATERIAL_ASSISTANT_HOME':str(profile),
             'MATERIAL_ASSISTANT_USER_HOME':str(profile/'user')}
        smoke=profile/'evidence'
        subprocess.run([str(app/'素材投放助手.exe'),'--smoke-ui',str(smoke)],
                       env=env,check=True,timeout=150,**flags)
        report=json.loads((smoke/'result.json').read_text(encoding='utf-8'))
        if not report.get('ok'):
            raise RuntimeError('Installed upgrade startup/processing check failed')
        for file in smoke.iterdir():
            if file.suffix in {'.json','.png'}:shutil.copy2(file,evidence/file.name)
        result={'ok':True,'obsolete_runtime_removed':True,'preserved_user_files':list(preserved_user_files),
                'installed_app_smoke_ok':True}
        (evidence/'upgrade-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer',required=True,type=Path)
    parser.add_argument('--evidence',required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(verify(args.installer,args.evidence),ensure_ascii=False))
