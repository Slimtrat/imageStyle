from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test-report":
        from artanimate.packaging_diagnostics import write_codec_self_test_report

        return write_codec_self_test_report(sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == "--qualify-v3":
        from artanimate.v3_qualification import write_v3_qualification_report

        return write_v3_qualification_report(sys.argv[2])

    from artanimate.desktop.app import main as run_desktop

    return run_desktop()


if __name__ == "__main__":
    raise SystemExit(main())
