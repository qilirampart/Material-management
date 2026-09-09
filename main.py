import json
import os
import sys

from src.paths import DATA_ROOT, prepare_environment


if __name__ == "__main__":
    prepare_environment()
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        from src.worker import main
        raise SystemExit(main(sys.argv[2]))
    if len(sys.argv) > 1 and sys.argv[1] == "--probe-douyin-video-url":
        from src.vendor.browser_probe import probe_cli
        raise SystemExit(probe_cli(sys.argv[2], sys.argv[3]))
    if len(sys.argv) > 1 and sys.argv[1] == "--smoke-ui":
        from src.desktop_diagnostics import smoke
        raise SystemExit(smoke(sys.argv[2]))
    try:
        desktop_config = json.loads(
            (DATA_ROOT / "runtime" / "desktop_config.json").read_text(encoding="utf-8-sig")
        )
    except (OSError, TypeError, ValueError):
        desktop_config = {}
    try:
        browser_debug_port = int(desktop_config.get("internal_browser_debug_port", 9233))
        if not 1 <= browser_debug_port <= 65535:
            raise ValueError
    except (TypeError, ValueError):
        browser_debug_port = 9233
    os.environ.setdefault("QTWEBENGINE_REMOTE_DEBUGGING", str(browser_debug_port))
    from src.desktop import main
    raise SystemExit(main())
