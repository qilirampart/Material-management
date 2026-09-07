from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from src.batch import LABELS, export_report, read_input, run_batch
from src.vision import ROOT


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="抖音视频下载与片头文字/logo抽检；不执行上传")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--input", required=True)
    run = commands.add_parser("run")
    run.add_argument("--input", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--config", default=str(ROOT / "config.example.json"))
    run.add_argument("--limit", type=int)
    run.add_argument("--resume", action="store_true")
    run.add_argument("--download-only", action="store_true")
    export = commands.add_parser("export")
    export.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        if args.command == "inspect":
            rows = read_input(args.input)
            print(json.dumps({"rows": len(rows), "unique_videos": len({r['video_id'] for r in rows if not r['input_error']}),
                              "invalid_rows": [r for r in rows if r['input_error']]}, ensure_ascii=False, default=str))
        elif args.command == "export":
            folder = Path(args.output)
            state = json.loads((folder / "results.json").read_text(encoding="utf-8"))
            export_report(state["input_rows"], state["records"], folder / "检测结果.xlsx")
        else:
            if args.limit is not None and args.limit < 1:
                raise ValueError("--limit 必须大于0")
            config = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
            state = run_batch(args.input, args.output, config, args.limit, args.resume, args.download_only)
            counts = Counter(LABELS[r["status"]] for r in state["records"].values())
            print(json.dumps(counts, ensure_ascii=False))
    except KeyboardInterrupt:
        print("已中断。已完成结果已保存，可使用 --resume 继续。")
        return 130
    except (ValueError, OSError) as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
