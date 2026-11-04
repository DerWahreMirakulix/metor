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
from scripts.release.semver import calculate_next_version, select_latest_stable_release


def main(argv: Sequence[str] | None = None) -> int:
    """Calculates and prints a release version for workflow consumption.

    Args:
        argv (Sequence[str] | None): Optional command-line arguments.

    Returns:
        int: Process status code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--release-type', choices=('current', 'patch', 'minor', 'major')
    )
    parser.add_argument('--previous-release')
    parser.add_argument('--available-release', action='append', default=[])
    parser.add_argument('--select-baseline', action='store_true')
    args = parser.parse_args(argv)
    selected_baseline: str | None = select_latest_stable_release(args.available_release)
    if args.select_baseline:
        if selected_baseline is not None:
            sys.stdout.write(selected_baseline + '\n')
        return 0
    if args.release_type is None:
        parser.error('--release-type is required unless --select-baseline is used')
    previous_release: str | None = args.previous_release or selected_baseline
    try:
        version: str = calculate_next_version(
            APP_VERSION,
            args.release_type,
            previous_release,
        )
    except ValueError as exc:
        sys.stderr.write(f'{exc}\n')
        return 1
    sys.stdout.write(version + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
