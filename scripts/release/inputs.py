"""Translate reviewed PyPI distribution digests into pip's native hash-checking mode."""

import argparse
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from scripts.release.paths import PROJECT_ROOT


HASH_FILE = PROJECT_ROOT / 'requirements' / 'release-distributions.sha256'
PIN = re.compile(r'([A-Za-z0-9_.-]+)==([^\s;]+)(.*)')
PIP_VERSION = '26.2.1'


def _key(name: str, version: str) -> tuple[str, str]:
    return re.sub(r'[-_.]+', '-', name).lower(), version


def hashed_requirements(locks: tuple[Path, ...], *, include_pip: bool = False) -> str:
    """Retain current exact pins/markers and require reviewed input bytes for each."""
    digests: dict[tuple[str, str], list[str]] = {}
    for line in HASH_FILE.read_text(encoding='utf-8').splitlines():
        digest, filename = line.split('  ')
        if not re.fullmatch('[a-f0-9]{64}', digest):
            raise ValueError(f'Invalid distribution digest for {filename}.')
        name, version, *_ = filename.removesuffix('.tar.gz').split('-')
        digests.setdefault(_key(name, version), []).append(digest)

    pins = {f'pip=={PIP_VERSION}'} if include_pip else set()
    pending = list(locks)
    seen: set[Path] = set()
    while pending:
        path = pending.pop().resolve()
        if path in seen:
            continue
        seen.add(path)
        for line in path.read_text(encoding='utf-8').splitlines():
            requirement = line.partition('#')[0].strip()
            if requirement.startswith('-r '):
                pending.append(path.parent / requirement[3:].strip())
            elif requirement:
                pins.add(requirement)

    lines: list[str] = []
    for requirement in sorted(pins):
        match = PIN.fullmatch(requirement)
        if not match:
            raise ValueError(f'Expected an exact version: {requirement}')
        hashes = digests.get(_key(match[1], match[2]))
        if not hashes:
            raise ValueError(f'Missing reviewed distribution hashes: {requirement}')
        lines.append(
            requirement + ''.join(f' --hash=sha256:{h}' for h in sorted(hashes))
        )
    return '\n'.join(lines) + '\n'


def install_build_environment() -> None:
    """Install the pinned native CPython 3.11 release toolchain before running project code."""
    root = PROJECT_ROOT / 'requirements'
    pip = [sys.executable, '-m', 'pip', '--isolated', 'install']
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'requirements.txt'
        path.write_text(
            hashed_requirements(
                tuple(
                    root / name for name in ('dev.lock', 'gui.lock', 'terminal.lock')
                ),
                include_pip=True,
            ),
            encoding='utf-8',
        )
        subprocess.run(
            [
                *pip,
                '--force-reinstall',
                '--only-binary=:all:',
                '--require-hashes',
                '-r',
                str(path),
            ],
            check=True,
        )
    local = ('packaging/sdk', '.', 'packaging/terminal', 'packaging/gui')
    subprocess.run(
        [
            *pip,
            '--no-deps',
            '--no-build-isolation',
            *(arg for project in local for arg in ('-e', project)),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--install-build-environment', action='store_true', required=True
    )
    parser.parse_args()
    install_build_environment()
