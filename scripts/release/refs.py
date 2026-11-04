"""Atomically publish the already-created release branch and annotated tag refs."""

import argparse
from pathlib import Path
import subprocess


def _validate_ref_component(value: str, namespace: str, cwd: Path) -> None:
    """Rejects malformed or option-like ref components through Git's own rules.

    Args:
        value: Short branch or tag name supplied by the controlled release job.
        namespace: Exact Git namespace containing the short name.
        cwd: Repository whose Git implementation validates the ref.
    Returns:
        None
    """
    if not value or value.startswith('-'):
        raise ValueError('Invalid release ref name.')
    subprocess.run(
        ['git', 'check-ref-format', f'{namespace}/{value}'],
        cwd=cwd,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def push_atomic_release_refs(
    repository: Path, remote: str, branch: str, tag: str
) -> None:
    """Updates the release branch and tag in one required atomic Git push.

    Args:
        repository: Checked-out repository containing HEAD and the annotated tag.
        remote: Configured Git remote name.
        branch: Destination branch short name.
        tag: Existing local release tag short name.
    Returns:
        None
    """
    if not remote or remote.startswith('-'):
        raise ValueError('Invalid release remote.')
    root = repository.resolve(strict=True)
    _validate_ref_component(branch, 'refs/heads', root)
    _validate_ref_component(tag, 'refs/tags', root)
    subprocess.run(
        [
            'git',
            'push',
            '--atomic',
            '--porcelain',
            remote,
            f'HEAD:refs/heads/{branch}',
            f'refs/tags/{tag}:refs/tags/{tag}',
        ],
        cwd=root,
        check=True,
    )


def main() -> None:
    """Parses the controlled release ref targets and performs the atomic push.

    Args:
        None
    Returns:
        None
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, default=Path.cwd())
    parser.add_argument('--remote', default='origin')
    parser.add_argument('--branch', required=True)
    parser.add_argument('--tag', required=True)
    args = parser.parse_args()
    push_atomic_release_refs(
        args.repository,
        args.remote,
        args.branch,
        args.tag,
    )


if __name__ == '__main__':
    main()
