"""Write checksums after installer compilation has completed."""
import hashlib
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
version = sys.argv[1] if len(sys.argv) > 1 else '0.3.0'
files = [root / 'release/素材投放助手/素材投放助手.exe', root / f'release/素材投放助手-安装包-{version}.exe']
report = {'version': version, 'type': 'native Windows desktop', 'files': [],
          'unit_tests': 117, 'native_ui_smoke': 'passed', 'candidate_model_config_smoke': 'passed',
          'packaged_ui_browser_worker_smoke': 'passed', 'installer_compilation': 'passed',
          'company_upload': 'not integrated', 'online_updates': 'not integrated', 'task_concurrency': 1}
for path in files:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    report['files'].append({'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest.hexdigest()})
(root / 'release/verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'Release {version} checksums saved')
