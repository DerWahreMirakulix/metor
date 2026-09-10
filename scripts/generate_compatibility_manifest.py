"""CLI entry point for generating the Metor release compatibility manifest."""

# ruff: noqa: E402

import argparse
import sys
from pathlib import Path
from typing import Sequence


PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / 'src'))
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.release.manifest import write_compatibility_manifest
from scripts.release.paths import API_SCHEMA_PATH, COMPATIBILITY_MANIFEST_PATH


def main(argv: Sequence[str] | None = None) -> int:
    """Generates the compatibility manifest at a deterministic location.

    Args:
        argv (Sequence[str] | None): Optional command-line arguments.

    Returns:
        int: Process status code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ipc-schema', type=Path, default=API_SCHEMA_PATH)
    parser.add_argument('--output', type=Path, default=COMPATIBILITY_MANIFEST_PATH)
    args = parser.parse_args(argv)
    write_compatibility_manifest(args.ipc_schema, args.output)
    sys.stdout.write(f'Compatibility manifest generated at {args.output}.\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
