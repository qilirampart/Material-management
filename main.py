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
    from src.desktop import main
    raise SystemExit(main())
