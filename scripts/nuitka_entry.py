"""Nuitka executable entry point, including an offscreen bundled-resource check."""

from __future__ import annotations

import sys


def main() -> int:
    # Nuitka does not set sys.frozen. Existing restart, elevation and helper lookup use it
    # to distinguish a standalone executable from a Python interpreter.
    sys.frozen = True
    if sys.argv[1:] == ["--check-runtime-resources"]:
        from scripts.check_runtime_resources import main as check_resources

        check_resources()
        return 0

    from nightreign_overlay.__main__ import main as run

    return run()


if __name__ == "__main__":
    sys.exit(main())
