"""Separate worker process; desktop remains responsive during network/FFmpeg work."""
import json
import sys
from pathlib import Path

from src.batch import error_summary, run_batch
from src.paths import prepare_environment


def main(request_path):
    prepare_environment()
    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    stop = Path(request.pop("stop_file"))
    log = Path(request_path).with_suffix(".events.jsonl")

    def emit(event):
        message = json.dumps(event, ensure_ascii=False)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
        if sys.stdout:
            print("@event " + message, flush=True)

    try:
        run_batch(**request, on_event=emit, should_stop=stop.exists)
        return 0
    except Exception as exc:
        emit({"type": "error", "message": error_summary(exc)})
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1]))
