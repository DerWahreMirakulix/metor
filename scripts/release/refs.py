"""Publish an annotated release tag for the approved main commit without writing a branch."""

import argparse
from pathlib import Path
import re
import subprocess

from scripts.release.semver import SemVer


def publish_tag(repository: Path, remote: str, tag: str, revision: str) -> None:
    """Create or verify the tag without replacing any existing remote ref."""
    if not re.fullmatch(r'[a-f0-9]{40}', revision) or tag != f'v{SemVer.parse(tag)}':
        raise ValueError(
            'Expected an immutable candidate SHA and canonical release tag.'
        )
    if not remote or remote.startswith('-'):
        raise ValueError('Invalid Git remote.')

    def git(*args: str) -> str:
        return subprocess.check_output(
            ['git', *args], cwd=repository, text=True
        ).strip()

    if git('rev-parse', 'HEAD') != revision:
        raise ValueError('Checkout is not the requested release candidate.')
    ref = f'refs/tags/{tag}'
    rows = git('ls-remote', remote, 'refs/heads/main', ref, ref + '^{}')
    refs = {name: sha for sha, name in (line.split() for line in rows.splitlines())}
    if refs.get('refs/heads/main') != revision:
        raise ValueError('main moved after release validation.')
    if ref in refs:
        if refs.get(ref + '^{}', refs[ref]) != revision:
            raise ValueError('Existing release tag has another target.')
        return
    git('tag', '-a', tag, revision, '-m', f'Metor {tag}')
    git('push', remote, f'{ref}:{ref}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remote', default='origin')
    parser.add_argument('--tag', required=True)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    publish_tag(Path.cwd(), args.remote, args.tag, args.revision)
