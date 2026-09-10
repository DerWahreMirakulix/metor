"""Developer CLI for inspecting and updating the central version registry."""

# ruff: noqa: E402

import argparse
import re
import sys
from pathlib import Path
from typing import Sequence


PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]
SRC_DIR: Path = PROJECT_ROOT / 'src'
REGISTRY_PATH: Path = SRC_DIR / 'metor' / 'versioning.py'

sys.path.insert(0, str(SRC_DIR))

from metor.versioning import format_version_matrix, validate_version_registry


CURRENT_CONSTANTS: dict[str, str] = {
    'ipc': 'IPC_PROTOCOL_VERSION',
    'peer': 'PEER_PROTOCOL_VERSION',
    'db-schema': 'DB_SCHEMA_VERSION',
    'keyslot': 'KEYSLOT_FORMAT_VERSION',
    'blob': 'BLOB_FORMAT_VERSION',
    'profile-key-derivation': 'PROFILE_KEY_DERIVATION_VERSION',
    'blob-object-derivation': 'BLOB_OBJECT_DERIVATION_VERSION',
}
MINIMUM_CONSTANTS: dict[str, str] = {
    'ipc': 'IPC_PROTOCOL_MIN_SUPPORTED',
    'peer': 'PEER_PROTOCOL_MIN_SUPPORTED',
    'db-schema': 'DB_SCHEMA_MIN_SUPPORTED',
    'keyslot': 'KEYSLOT_FORMAT_MIN_SUPPORTED',
    'blob': 'BLOB_FORMAT_MIN_SUPPORTED',
}
SEMVER_PATTERN: re.Pattern[str] = re.compile(
    r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$'
)


def _replace_integer(constant_name: str, new_value: int) -> None:
    """Replaces one integer assignment in the authoritative registry.

    Args:
        constant_name (str): Exact registry constant to replace.
        new_value (int): Positive replacement generation.

    Raises:
        ValueError: If the requested value or registry shape is invalid.

    Returns:
        None
    """
    if new_value < 1:
        raise ValueError('Compatibility generations must be at least 1.')
    source: str = REGISTRY_PATH.read_text(encoding='utf-8')
    pattern: re.Pattern[str] = re.compile(
        rf'^{re.escape(constant_name)}: int = (\d+)$', re.MULTILINE
    )
    match = pattern.search(source)
    if match is None:
        raise ValueError(f'Central registry assignment not found: {constant_name}')
    updated: str = pattern.sub(f'{constant_name}: int = {new_value}', source, count=1)
    REGISTRY_PATH.write_text(updated, encoding='utf-8')


def _read_integer(constant_name: str) -> int:
    """Reads one integer assignment from the authoritative registry.

    Args:
        constant_name (str): Exact registry constant to inspect.

    Raises:
        ValueError: If the registry assignment cannot be found.

    Returns:
        int: Current assigned generation.
    """
    source: str = REGISTRY_PATH.read_text(encoding='utf-8')
    match = re.search(
        rf'^{re.escape(constant_name)}: int = (\d+)$', source, re.MULTILINE
    )
    if match is None:
        raise ValueError(f'Central registry assignment not found: {constant_name}')
    return int(match.group(1))


def bump_axis(axis: str) -> None:
    """Increments one explicit compatibility generation.

    Args:
        axis (str): Stable compatibility-axis name.

    Returns:
        None
    """
    constant_name: str = CURRENT_CONSTANTS[axis]
    _replace_integer(constant_name, _read_integer(constant_name) + 1)


def set_minimum(axis: str, new_value: int) -> None:
    """Sets an explicitly reviewed minimum-supported generation.

    Args:
        axis (str): Compatibility axis with a support range.
        new_value (int): Oldest generation the implementation accepts.

    Returns:
        None
    """
    current: int = _read_integer(CURRENT_CONSTANTS[axis])
    if new_value > current:
        raise ValueError('Minimum supported cannot exceed the current generation.')
    _replace_integer(MINIMUM_CONSTANTS[axis], new_value)


def set_application_version(version: str) -> None:
    """Sets the application SemVer used by explicit release automation.

    Args:
        version (str): Valid stable application Semantic Version.

    Raises:
        ValueError: If the value is not a supported Semantic Version.

    Returns:
        None
    """
    if SEMVER_PATTERN.fullmatch(version) is None:
        raise ValueError(f'Invalid Metor Semantic Version: {version}')
    source: str = REGISTRY_PATH.read_text(encoding='utf-8')
    pattern: re.Pattern[str] = re.compile(r"^APP_VERSION: str = '[^']+'$", re.MULTILINE)
    if pattern.search(source) is None:
        raise ValueError('Central APP_VERSION assignment not found.')
    REGISTRY_PATH.write_text(
        pattern.sub(f"APP_VERSION: str = '{version}'", source, count=1),
        encoding='utf-8',
    )


def build_parser() -> argparse.ArgumentParser:
    """Builds the versioning command-line parser.

    Args:
        None

    Returns:
        argparse.ArgumentParser: Configured parser.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True)
    subparsers.add_parser('status', help='Print the complete version matrix.')
    subparsers.add_parser('validate', help='Validate registry invariants.')

    bump_parser = subparsers.add_parser(
        'bump', help='Explicitly bump one compatibility generation.'
    )
    bump_parser.add_argument('axis', choices=tuple(CURRENT_CONSTANTS))

    min_parser = subparsers.add_parser(
        'set-min', help='Set one explicitly reviewed minimum-supported value.'
    )
    min_parser.add_argument('axis', choices=tuple(MINIMUM_CONSTANTS))
    min_parser.add_argument('version', type=int)

    app_parser = subparsers.add_parser(
        'set-app', help='Set APP_VERSION for explicit release automation.'
    )
    app_parser.add_argument('version')
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Runs the central version-registry command.

    Args:
        argv (Sequence[str] | None): Optional command arguments.

    Returns:
        int: Process status code.
    """
    args = build_parser().parse_args(argv)
    try:
        if args.command == 'status':
            sys.stdout.write(format_version_matrix() + '\n')
        elif args.command == 'validate':
            errors: tuple[str, ...] = validate_version_registry()
            if errors:
                sys.stderr.write('\n'.join(errors) + '\n')
                return 1
            sys.stdout.write('Version registry is valid.\n')
        elif args.command == 'bump':
            bump_axis(args.axis)
        elif args.command == 'set-min':
            set_minimum(args.axis, args.version)
        elif args.command == 'set-app':
            set_application_version(args.version)
    except ValueError as exc:
        sys.stderr.write(f'{exc}\n')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
