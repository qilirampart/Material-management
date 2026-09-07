"""Run the packaged executable, embedded browser, and worker without system Python/FFmpeg."""
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "release/素材投放助手/素材投放助手.exe"
folder = ROOT / "output/package_smoke"
folder.mkdir(parents=True, exist_ok=True)
env = dict(os.environ)
env["MATERIAL_ASSISTANT_HOME"] = str(folder)
env["QT_QPA_PLATFORM"] = "offscreen"
env["PATH"] = str(Path(os.environ.get("WINDIR", "C:/Windows")) / "System32")
ui = folder / "ui"
result = subprocess.run([str(EXE), "--smoke-ui", str(ui)], env=env, cwd=folder, timeout=50,
                        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
if result.returncode or not (ui / "result.json").exists():
    (folder / "diagnostic-stderr.txt").write_bytes(result.stderr)
    raise SystemExit(f"Packaged UI failed: {result.returncode}")
report = json.loads((ui / "result.json").read_text(encoding="utf-8"))
assert report["ok"], report
batch = folder / "batch"
(batch / "videos").mkdir(parents=True, exist_ok=True)
source = ROOT / "output/pilot/videos/7681538825608236331.mp4"
shutil.copy2(source, batch / "videos" / source.name)
config = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
request = folder / "worker.json"
request.write_text(json.dumps({"input_path": str(ROOT / "懂小剧素材_婚房门后的秘密.xlsx"), "output": str(batch),
                              "config": config, "resume": True, "download_only": True,
                              "selected_ids": [source.stem], "stop_file": str(folder / "stop")}, ensure_ascii=False), encoding="utf-8")
worker = subprocess.run([str(EXE), "--worker", str(request)], env=env, cwd=folder, timeout=90,
                        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
assert worker.returncode == 0, worker.returncode
state = json.loads((batch / "results.json").read_text(encoding="utf-8"))
assert state["records"][source.stem]["download"] == "已下载"
assert state["records"][source.stem]["status"] == "review_required"
assert (batch / "检测结果.xlsx").is_file()
print("package-smoke-ok: native UI, embedded browser, bundled FFmpeg, frozen worker, Excel export")
