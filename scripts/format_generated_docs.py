"""Applies the repository-pinned formatter without network resolution or fallback."""

import json
from pathlib import Path
import subprocess


def format_document(path: Path) -> None:
    """Formats canonical Markdown using the lockfile-installed local tool.

    Args:
        path (Path): Generated Markdown document.

    Returns:
        None
    """
    root = Path(__file__).resolve().parents[1]
    package = root / 'node_modules' / 'prettier'
    expected = json.loads((root / 'package.json').read_text(encoding='utf-8'))[
        'devDependencies'
    ]['prettier']
    installed = json.loads((package / 'package.json').read_text(encoding='utf-8'))[
        'version'
    ]
    if installed != expected:
        raise RuntimeError('Pinned Prettier is not installed; run npm ci.')
    subprocess.run(
        [
            'node',
            str(package / 'bin' / 'prettier.cjs'),
            '--end-of-line',
            'lf',
            '--write',
            str(path.resolve()),
        ],
        cwd=root,
        check=True,
    )
