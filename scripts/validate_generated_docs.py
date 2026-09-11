"""Verifies checked-in generated documentation freshness and reproducibility."""

# ruff: noqa: E402

import subprocess
import sys
import hashlib
from pathlib import Path
from typing import Sequence


PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / 'src'))
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.release.paths import (
    API_DOC_PATH,
    API_SCHEMA_PATH,
    COMPATIBILITY_MANIFEST_PATH,
    SETTINGS_DOC_PATH,
)


GENERATOR_PATHS: tuple[Path, ...] = (
    PROJECT_ROOT / 'scripts' / 'generate_api_docs.py',
    PROJECT_ROOT / 'scripts' / 'generate_settings_docs.py',
    PROJECT_ROOT / 'scripts' / 'generate_compatibility_manifest.py',
)
GENERATED_ARTIFACT_PATHS: tuple[Path, ...] = (
    API_DOC_PATH,
    SETTINGS_DOC_PATH,
    API_SCHEMA_PATH,
    COMPATIBILITY_MANIFEST_PATH,
)


def run_generators() -> None:
    """Executes every canonical generated-document producer in order.

    Args:
        None

    Returns:
        None
    """
    for generator_path in GENERATOR_PATHS:
        subprocess.run(
            [sys.executable, str(generator_path)],
            cwd=PROJECT_ROOT,
            check=True,
        )


def generated_artifacts() -> dict[Path, bytes]:
    """Reads the exact generated output used for reproducibility validation.

    Args:
        None

    Returns:
        dict[Path, bytes]: Artifact content keyed by canonical path.
    """
    return {path: path.read_bytes() for path in GENERATED_ARTIFACT_PATHS}


def validate_reproducibility() -> tuple[Path, ...]:
    """Reports stale originals as well as non-deterministic second-generation output.

    Args:
        None

    Returns:
        tuple[Path, ...]: Stale or non-deterministic canonical artifacts.
    """
    original = generated_artifacts()
    run_generators()
    first_generation: dict[Path, bytes] = generated_artifacts()
    run_generators()
    second_generation: dict[Path, bytes] = generated_artifacts()
    changed = []
    for path in GENERATED_ARTIFACT_PATHS:
        stale = original[path] != first_generation[path]
        unstable = first_generation[path] != second_generation[path]
        if stale or unstable:
            changed.append(path)
            print(f'{path}: stale={stale}, non-deterministic={unstable}')
            for label, data in (
                ('original', original[path]),
                ('first', first_generation[path]),
                ('second', second_generation[path]),
            ):
                crlf = data.count(b'\r\n')
                print(
                    f'  {label}: bytes={len(data)}, CRLF={crlf}, '
                    f'sha256={hashlib.sha256(data).hexdigest()}'
                )
    return tuple(changed)


def main(argv: Sequence[str] | None = None) -> int:
    """Validates canonical generated documentation is idempotent.

    Args:
        argv (Sequence[str] | None): Unused command-line arguments.

    Returns:
        int: Process status code.
    """
    del argv
    changed_paths: tuple[Path, ...] = validate_reproducibility()
    if changed_paths:
        for path in changed_paths:
            print(f'Generated artifact was stale or non-deterministic: {path}')
        return 1
    print('Generated documentation is fresh and reproducible.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
