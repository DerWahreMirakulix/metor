"""CLI entry point for checking a candidate release compatibility manifest."""

# ruff: noqa: E402

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence, cast


PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / 'src'))
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.release.compatibility import compare_manifests


def _read_manifest(path: Path) -> dict[str, Any]:
    """Reads one JSON compatibility manifest.

    Args:
        path (Path): Manifest path.

    Returns:
        dict[str, Any]: Parsed manifest document.
    """
    return cast(dict[str, Any], json.loads(path.read_text(encoding='utf-8')))


def main(argv: Sequence[str] | None = None) -> int:
    """Runs first-release or historical compatibility validation.

    Args:
        argv (Sequence[str] | None): Optional command-line arguments.

    Returns:
        int: Process status code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--previous', type=Path)
    parser.add_argument(
        '--peer-classification',
        choices=('unchanged', 'additive', 'breaking'),
        default='unchanged',
    )
    parser.add_argument('--crypto-migration-reviewed', action='store_true')
    args = parser.parse_args(argv)
    previous = _read_manifest(args.previous) if args.previous is not None else None
    report = compare_manifests(
        previous,
        _read_manifest(args.current),
        args.peer_classification,
        args.crypto_migration_reviewed,
    )
    for note in report.notes:
        sys.stdout.write(f'NOTE: {note}\n')
    for error in report.errors:
        sys.stderr.write(f'ERROR: {error}\n')
    return 1 if report.errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
