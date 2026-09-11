"""Validates that all Metor wheel variants use the central application version."""

# ruff: noqa: E402

import argparse
import email.parser
import sys
from pathlib import Path
from typing import Sequence
from zipfile import ZipFile


PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from metor.versioning import APP_VERSION


def wheel_metadata(wheel_path: Path) -> tuple[str, str, tuple[str, ...]]:
    """Reads a wheel's distribution name, version, and requirements.

    Args:
        wheel_path (Path): Built wheel archive.

    Raises:
        ValueError: If the wheel has no unique core metadata document.

    Returns:
        tuple[str, str, tuple[str, ...]]: Distribution name, version, and
            declared dependency requirements.
    """
    with ZipFile(wheel_path) as archive:
        metadata_names: list[str] = [
            name for name in archive.namelist() if name.endswith('.dist-info/METADATA')
        ]
        if len(metadata_names) != 1:
            raise ValueError(f'Wheel has invalid metadata layout: {wheel_path}')
        payload: str = archive.read(metadata_names[0]).decode('utf-8')
    metadata = email.parser.Parser().parsestr(payload)
    return (
        metadata['Name'],
        metadata['Version'],
        tuple(metadata.get_all('Requires-Dist', [])),
    )


def wheel_owned_files(wheel_path: Path) -> set[str]:
    """Returns installed namespace files, excluding distribution metadata."""
    with ZipFile(wheel_path) as archive:
        return {
            name
            for name in archive.namelist()
            if name.startswith('metor/') and '.dist-info/' not in name
        }


def validate_wheel_versions(wheel_paths: Sequence[Path]) -> tuple[str, ...]:
    """Checks all three release distributions against ``APP_VERSION``.

    Args:
        wheel_paths (Sequence[Path]): Candidate Metor wheels.

    Returns:
        tuple[str, ...]: Validation errors; empty on success.
    """
    expected_names: set[str] = {'metor', 'metor-sdk', 'metor-ui-terminal'}
    found_names: set[str] = set()
    ownership: dict[str, set[str]] = {}
    errors: list[str] = []
    for wheel_path in wheel_paths:
        name, version, requirements = wheel_metadata(wheel_path)
        if name not in expected_names:
            continue
        found_names.add(name)
        ownership[name] = wheel_owned_files(wheel_path)
        if version != APP_VERSION:
            errors.append(f'{name} reports {version}; expected {APP_VERSION}.')
        if name == 'metor':
            expected_sdk: str = f'metor-sdk=={APP_VERSION}'
            if expected_sdk not in requirements:
                errors.append(
                    f'metor must require {expected_sdk}; found '
                    f'{", ".join(requirements) or "no dependencies"}.'
                )
        if name == 'metor-ui-terminal':
            expected_requirements = (
                f'metor=={APP_VERSION}',
                f'metor-sdk=={APP_VERSION}',
            )
            for expected_requirement in expected_requirements:
                if expected_requirement not in requirements:
                    errors.append(
                        'metor-ui-terminal must require '
                        f'{expected_requirement}; found '
                        f'{", ".join(requirements) or "no dependencies"}.'
                    )
    missing: set[str] = expected_names - found_names
    if missing:
        errors.append(f'Missing Metor wheels: {", ".join(sorted(missing))}.')
    for left_index, left in enumerate(sorted(ownership)):
        for right in sorted(ownership)[left_index + 1 :]:
            overlap = ownership[left] & ownership[right]
            if overlap:
                errors.append(
                    f'{left} and {right} overlap: {", ".join(sorted(overlap))}.'
                )
    return tuple(errors)


def main(argv: Sequence[str] | None = None) -> int:
    """Runs wheel metadata validation.

    Args:
        argv (Sequence[str] | None): Optional wheel paths or glob roots.

    Returns:
        int: Process status code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheel_paths', nargs='+', type=Path)
    args = parser.parse_args(argv)
    errors: tuple[str, ...] = validate_wheel_versions(args.wheel_paths)
    for error in errors:
        sys.stderr.write(error + '\n')
    if errors:
        return 1
    sys.stdout.write(f'All Metor wheels report {APP_VERSION}.\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
