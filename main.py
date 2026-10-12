"""Source / PyInstaller entry point.

Allows running the app without installing the package: ``python main.py``.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from nightreign_overlay.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
