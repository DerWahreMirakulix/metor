"""CLI entry point for building one self-contained release wheel bundle."""

# ruff: noqa: E402

import sys
from pathlib import Path


SCRIPT_DIR: Path = Path(__file__).parent.resolve()
PROJECT_ROOT: Path = SCRIPT_DIR.parent

sys.path.insert(0, str(PROJECT_ROOT))

from scripts.release.bundle import main


if __name__ == '__main__':
    main()
