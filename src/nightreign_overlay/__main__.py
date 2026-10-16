"""``python -m nightreign_overlay`` entry point."""

from __future__ import annotations

import contextlib
import io
import sys


def main() -> int:
    from nightreign_overlay.platforms.elevation import ensure_administrator

    exit_code = ensure_administrator()
    if exit_code is not None:
        return exit_code

    # qfluentwidgets prints a promotional banner when first imported; keep the console clean.
    with contextlib.redirect_stdout(io.StringIO()):
        import qfluentwidgets  # noqa: F401

    from nightreign_overlay.app import run

    return run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
