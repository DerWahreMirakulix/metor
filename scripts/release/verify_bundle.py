"""Offline bundle target and checksum verification using only the Python stdlib."""

import argparse
import hashlib
import json
import platform
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Sequence, cast


CHECKSUM_FILE_NAME = 'SHA256SUMS.txt'
METADATA_FILE_NAME = 'BUNDLE.json'
CHECKSUM_PATTERN = re.compile(r'^([0-9a-f]{64})  (.+)$')


def normalize_machine(machine: str) -> str:
    """Normalizes common architecture aliases used by bundle metadata.

    Args:
        machine: Runtime architecture reported by Python.

    Returns:
        str: Stable architecture label.
    """
    normalized = machine.strip().lower()
    return {
        'amd64': 'x86_64',
        'x64': 'x86_64',
        'x86-64': 'x86_64',
        'aarch64': 'arm64',
    }.get(normalized, normalized or 'unknown')


def read_metadata(bundle_dir: Path) -> dict[str, object]:
    """Reads the declared immutable build target from one bundle.

    Args:
        bundle_dir: Extracted bundle directory.

    Returns:
        dict[str, object]: Parsed target metadata.
    """
    document = json.loads((bundle_dir / METADATA_FILE_NAME).read_text(encoding='utf-8'))
    if not isinstance(document, dict):
        raise ValueError('Bundle target metadata must be a JSON object.')
    return cast(dict[str, object], document)


def target_errors(metadata: dict[str, object]) -> tuple[str, ...]:
    """Compares the running interpreter and host with bundle target metadata.

    Args:
        metadata: Parsed bundle target document.

    Returns:
        tuple[str, ...]: Exact incompatibilities; empty for a matching target.
    """
    expected_python = metadata.get('python')
    expected_system = metadata.get('system')
    expected_machine = metadata.get('machine')
    expected_abi = metadata.get('abi')
    actual_python = f'{sys.version_info.major}.{sys.version_info.minor}'
    actual_system = platform.system().strip().lower()
    actual_machine = normalize_machine(platform.machine())
    actual_abi = sys.implementation.cache_tag
    errors: list[str] = []
    for label, expected, actual in (
        ('Python minor', expected_python, actual_python),
        ('operating system', expected_system, actual_system),
        ('architecture', expected_machine, actual_machine),
        ('CPython ABI', expected_abi, actual_abi),
    ):
        if expected != actual:
            errors.append(f'Bundle requires {label} {expected!r}; found {actual!r}.')
    if sys.implementation.name != 'cpython':
        errors.append('Bundle requires CPython.')
    return tuple(errors)


def checksum_entries(bundle_dir: Path) -> dict[PurePosixPath, str]:
    """Parses a complete, duplicate-free checksum manifest.

    Args:
        bundle_dir: Extracted bundle directory.

    Returns:
        dict[PurePosixPath, str]: Relative bundle paths mapped to SHA-256 values.
    """
    entries: dict[PurePosixPath, str] = {}
    lines = (bundle_dir / CHECKSUM_FILE_NAME).read_text(encoding='utf-8').splitlines()
    for line in lines:
        match = CHECKSUM_PATTERN.fullmatch(line)
        if match is None:
            raise ValueError('Malformed SHA256SUMS.txt entry.')
        relative = PurePosixPath(match.group(2))
        if relative.is_absolute() or '..' in relative.parts or not relative.parts:
            raise ValueError('Unsafe SHA256SUMS.txt path.')
        if relative in entries:
            raise ValueError(f'Duplicate checksum path: {relative}.')
        entries[relative] = match.group(1)
    return entries


def verify_checksums(bundle_dir: Path) -> None:
    """Verifies manifest completeness and every supplied artifact hash.

    Args:
        bundle_dir: Extracted bundle directory.

    Raises:
        ValueError: If a file is missing, unexpected, unsafe, or modified.

    Returns:
        None
    """
    entries = checksum_entries(bundle_dir)
    actual = {
        PurePosixPath(path.relative_to(bundle_dir).as_posix())
        for path in bundle_dir.rglob('*')
        if path.is_file()
        and path.name != CHECKSUM_FILE_NAME
        and '.venv' not in path.relative_to(bundle_dir).parts
    }
    expected = set(entries)
    if missing := expected - actual:
        raise ValueError(
            f'Missing bundle files: {", ".join(map(str, sorted(missing)))}.'
        )
    if unexpected := actual - expected:
        raise ValueError(
            f'Unhashed bundle files: {", ".join(map(str, sorted(unexpected)))}.'
        )
    for relative, expected_digest in entries.items():
        path = bundle_dir.joinpath(*relative.parts)
        actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_digest != expected_digest:
            raise ValueError(f'Checksum mismatch: {relative}.')


def verify_bundle(bundle_dir: Path, *, target_only: bool = False) -> None:
    """Validates target compatibility and optionally complete bundle integrity.

    The checksum manifest proves internal integrity only. It is not a signature
    and makes no provenance or publisher-authenticity claim.

    Args:
        bundle_dir: Extracted release bundle.
        target_only: Skip hashes while selecting an interpreter.

    Raises:
        ValueError: If the interpreter, host, manifest, or files are invalid.

    Returns:
        None
    """
    errors = target_errors(read_metadata(bundle_dir))
    if errors:
        raise ValueError('\n'.join(errors))
    if not target_only:
        verify_checksums(bundle_dir)


def main(argv: Sequence[str] | None = None) -> int:
    """Runs the standalone verifier shipped inside every offline bundle.

    Args:
        argv: Optional command arguments.

    Returns:
        int: Process status.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle_dir', type=Path)
    parser.add_argument('--target-only', action='store_true')
    args = parser.parse_args(argv)
    try:
        verify_bundle(args.bundle_dir.resolve(), target_only=args.target_only)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(f'Bundle verification failed: {exc}\n')
        return 1
    print('Bundle target and integrity verified.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
