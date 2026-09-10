"""CLI entry point for calculating the next Metor application release version."""

# ruff: noqa: E402

import argparse
import sys
from pathlib import Path
from typing import Sequence


PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / 'src'))
sys.path.insert(0, str(PROJECT_ROOT))

from metor.versioning import APP_VERSION
from scripts.release.semver import calculate_next_version


def main(argv: Sequence[str] | None = None) -> int:
    """Calculates and prints a release version for workflow consumption.

    Args:
        argv (Sequence[str] | None): Optional command-line arguments.

    Returns:
        int: Process status code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--release-type', choices=('current', 'patch', 'minor', 'major'), required=True
    )
    parser.add_argument(
        '--prerelease', choices=('none', 'alpha', 'beta', 'rc'), default='none'
    )
    parser.add_argument('--previous-release')
    args = parser.parse_args(argv)
    try:
        version: str = calculate_next_version(
            APP_VERSION,
            args.release_type,
            args.prerelease,
            args.previous_release,
        )
    except ValueError as exc:
        sys.stderr.write(f'{exc}\n')
        return 1
    sys.stdout.write(version + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
