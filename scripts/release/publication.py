"""Validate the exact eight release ZIPs and resume publication of one verified draft."""

import argparse
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
from typing import Any, cast
from zipfile import ZipExtFile, ZipFile

from scripts.release.bundle import RELEASE_VARIANTS, build_bundle_name
from scripts.release.verify_bundle import CHECKSUM_PATTERN, file_digest


RELEASE_PLATFORMS = ('linux', 'windows')


def verify_archive(archive: ZipFile, root: str) -> None:
    """Stream every native-tested member through the complete in-archive hash manifest."""
    files = []
    for item in archive.infolist():
        raw = item.filename.removesuffix('/')
        path = PurePosixPath(raw)
        if (
            not path.parts
            or path.parts[0] != root
            or path.as_posix() != raw
            or '..' in path.parts
            or '\\' in raw
            or ':' in raw
            or stat.S_ISLNK(item.external_attr >> 16)
        ):
            raise ValueError('Unsafe entry in native release archive.')
        if not item.is_dir():
            files.append(item.filename)
    manifest = f'{root}/SHA256SUMS.txt'
    if len(set(files)) != len(files) or manifest not in files:
        raise ValueError('Missing manifest or duplicate archive entry.')
    expected = {}
    for line in archive.read(manifest).decode('utf-8').splitlines():
        match = CHECKSUM_PATTERN.fullmatch(line)
        if match is None:
            raise ValueError('Invalid release checksum line.')
        relative = PurePosixPath(match[2])
        if (
            relative.is_absolute()
            or '..' in relative.parts
            or relative.as_posix() != match[2]
            or '\\' in match[2]
            or ':' in match[2]
        ):
            raise ValueError('Unsafe archive checksum path.')
        name = f'{root}/{relative}'
        if name in expected:
            raise ValueError('Duplicate archive checksum entry.')
        expected[name] = match[1]
    if set(files) - {manifest} != set(expected):
        raise ValueError('Archive checksum inventory is incomplete.')
    for name, digest in expected.items():
        with archive.open(name) as handle:
            if (
                hashlib.file_digest(cast(ZipExtFile, handle), 'sha256').hexdigest()
                != digest
            ):
                raise ValueError(f'Archive payload digest mismatch: {name}')


def archive_inventory(directory: Path, revision: str, version: str) -> dict[str, str]:
    """Bind every expected package and native target to the tested SHA and archive digest."""
    if not re.fullmatch(r'[a-f0-9]{40}', revision):
        raise ValueError('A full candidate commit is required.')
    expected = {
        build_bundle_name(system, 'x86_64', 3, 11, variant): (system, variant)
        for system in RELEASE_PLATFORMS
        for variant in RELEASE_VARIANTS
    }
    if {path.name for path in directory.iterdir()} != {
        name + '.zip' for name in expected
    }:
        raise ValueError('Release requires exactly eight platform archives.')
    digests: dict[str, str] = {}
    for name, (system, variant) in sorted(expected.items()):
        path = directory / (name + '.zip')
        with ZipFile(path) as archive:
            verify_archive(archive, name)
            package = {
                'sdk': 'metor-sdk',
                'base': 'metor',
                'terminal': 'metor-ui-terminal',
                'gui': 'metor-ui-gui',
            }[variant]
            package_wheel = package.replace('-', '_') + f'-{version}-py3-none-any.whl'
            required_files = (
                'install.sh',
                'install.cmd',
                'verify_bundle.py',
                'INSTALL.txt',
                'NATIVE-COMPONENTS.json',
                f'wheelhouse/{package_wheel}',
            )
            if any(
                f'{name}/{member}' not in archive.namelist()
                for member in required_files
            ):
                raise ValueError(f'Required installer input missing: {path.name}')
            metadata = json.loads(archive.read(f'{name}/BUNDLE.json'))
        required = {
            'package': package,
            'system': system,
            'machine': 'x86_64',
            'python': '3.11',
            'abi': 'cpython-311',
            'variant': variant,
            'source_revision': revision,
            'application_version': version,
        }
        if any(metadata.get(key) != value for key, value in required.items()):
            raise ValueError(f'Archive identity mismatch: {path.name}')
        digests[path.name] = 'sha256:' + file_digest(path)
    return digests


@dataclass(frozen=True)
class RemoteRelease:
    """The published/draft identity and asset byte digests reported by GitHub."""

    id: int
    draft: bool
    target: str
    body: str
    assets: dict[str, str]
    empty_uploads: dict[str, int] = field(default_factory=dict)


class GitHub:
    """Invoke the installed GitHub CLI using the workflow's scoped repository token."""

    def __init__(self, repository: str) -> None:
        self.repository = repository
        self.endpoint = f'repos/{repository}'

    def _api(self, endpoint: str, *options: str) -> Any:
        raw = subprocess.check_output(
            ['gh', 'api', self.endpoint + endpoint, *options], text=True
        )
        return json.loads(raw) if raw else None

    def release(self, tag: str) -> RemoteRelease | None:
        pages = self._api('/releases?per_page=100', '--paginate', '--slurp')
        matches = [r for page in pages for r in page if r['tag_name'] == tag]
        if len(matches) > 1:
            raise ValueError('Ambiguous draft or release tag.')
        if not matches:
            return None
        r = matches[0]
        pages = self._api(
            f'/releases/{r["id"]}/assets?per_page=100', '--paginate', '--slurp'
        )
        assets: dict[str, str] = {}
        empty_uploads: dict[str, int] = {}
        for page in pages:
            for asset in page:
                name = asset['name']
                if name in assets or name in empty_uploads:
                    raise ValueError('Duplicate GitHub asset.')
                if (
                    asset['state'] == 'starter'
                    and asset['size'] == 0
                    and not asset.get('digest')
                ):
                    empty_uploads[name] = asset['id']
                    continue
                if asset['state'] != 'uploaded':
                    raise ValueError('Unexpected remote upload state.')
                assets[asset['name']] = asset['digest']
        return RemoteRelease(
            r['id'],
            r['draft'],
            r['target_commitish'],
            '\n'.join((r['body'] or '').splitlines()),
            assets,
            empty_uploads,
        )

    def verify_candidate(self, revision: str) -> None:
        if self._api('/git/ref/heads/main')['object']['sha'] != revision:
            raise ValueError('main moved after release validation.')
        # Bind the result to the push workflow, SHA and repository, not a check name alone.
        runs = self._api(
            f'/actions/workflows/ci.yml/runs?event=push&branch=main&head_sha={revision}&per_page=1'
        )['workflow_runs']
        if (
            not runs
            or runs[0]['head_repository']['full_name'] != self.repository
            or runs[0]['head_sha'] != revision
            or runs[0]['conclusion'] != 'success'
        ):
            raise ValueError('Required CI for this main SHA has not succeeded.')
        pages = self._api(
            f'/actions/runs/{runs[0]["id"]}/jobs?per_page=100', '--paginate', '--slurp'
        )
        required = [
            j['conclusion']
            for page in pages
            for j in page['jobs']
            if j['name'] == 'Required CI result'
        ]
        if required != ['success']:
            raise ValueError('Missing successful Required CI result on candidate.')

    def verify_build_run(self, run_id: str, revision: str) -> None:
        if not re.fullmatch(r'[1-9][0-9]*', run_id):
            raise ValueError('Invalid build run ID.')
        run = self._api(f'/actions/runs/{run_id}')
        if (
            run['head_sha'] != revision
            or run['event'] != 'workflow_dispatch'
            or run['head_branch'] != 'main'
            or run['path'] != '.github/workflows/release.yml'
            or run['head_repository']['full_name'] != self.repository
        ):
            raise ValueError(
                'Draft artifacts originate from a different workflow or revision.'
            )

    def create(self, tag: str, revision: str, body: str) -> None:
        self._api(
            '/releases',
            '--method',
            'POST',
            '-f',
            f'tag_name={tag}',
            '-f',
            f'target_commitish={revision}',
            '-f',
            f'name={tag}',
            '-f',
            f'body={body}',
            '-F',
            'draft=true',
        )

    def remove_empty_upload(self, asset_id: int) -> None:
        self._api(f'/releases/assets/{asset_id}', '--method', 'DELETE')

    def upload(self, tag: str, path: Path) -> None:
        subprocess.run(
            ['gh', 'release', 'upload', tag, str(path), '--repo', self.repository],
            check=True,
        )

    def publish(self, release_id: int) -> None:
        self._api(f'/releases/{release_id}', '--method', 'PATCH', '-F', 'draft=false')

    def verify_tag(self, tag: str, revision: str) -> None:
        # A draft may have reserved its name before the tag exists. A publishable
        # release must reference the reviewed commit even after an upload retry.
        peeled = subprocess.check_output(
            [
                'git',
                'ls-remote',
                '--tags',
                'origin',
                f'refs/tags/{tag}',
                f'refs/tags/{tag}^{{}}',
            ],
            text=True,
        )
        refs = {ref: sha for sha, ref in (line.split() for line in peeled.splitlines())}
        if refs.get(f'refs/tags/{tag}^{{}}', refs.get(f'refs/tags/{tag}')) != revision:
            raise ValueError('Release tag differs from the approved commit.')


def source_run(release: RemoteRelease | None, revision: str, run_id: str) -> str:
    """Recover a previous draft's accepted artifact run after a workflow retry."""
    if release is None:
        return run_id
    match = re.search(r'^Build run: ([1-9][0-9]*)$', release.body, re.MULTILINE)
    if (
        release.target not in (revision, 'main')
        or f'Candidate: {revision}' not in release.body.splitlines()
        or match is None
    ):
        raise ValueError('Existing release is not bound to this candidate and build.')
    return match[1]


def publish(
    github: GitHub, tag: str, revision: str, source: str, directory: Path, status: str
) -> None:
    """Upload missing bytes only, confirm the complete digest set, and then publish."""
    digests = archive_inventory(directory, revision, tag.removeprefix('v'))
    table = '\n'.join(f'- `{name}` `{digest}`' for name, digest in digests.items())
    body = f'Candidate: {revision}\nBuild run: {source}\n\n```text\n{status.strip()}\n```\n\n{table}\n'
    remote = github.release(tag)
    github.verify_candidate(revision)
    github.verify_tag(tag, revision)
    if remote is None:
        github.create(tag, revision, body)
        remote = github.release(tag)
    if (
        remote is None
        or remote.target not in (revision, 'main')
        or remote.body.strip() != body.strip()
    ):
        raise ValueError('Draft identity or approved archive inventory has changed.')
    if any(digests.get(name) != digest for name, digest in remote.assets.items()):
        raise ValueError('An existing release asset differs from the verified build.')
    if remote.empty_uploads and (
        not remote.draft or set(remote.empty_uploads) - digests.keys()
    ):
        raise ValueError('Unexpected incomplete upload.')
    if not remote.draft:
        if remote.assets != digests:
            raise ValueError('Published release is incomplete.')
        return
    for asset_id in remote.empty_uploads.values():
        github.remove_empty_upload(asset_id)
    for name in sorted(digests.keys() - remote.assets.keys()):
        github.upload(tag, directory / name)
    uploaded = github.release(tag)
    if (
        uploaded is None
        or uploaded.id != remote.id
        or uploaded.target not in (revision, 'main')
        or uploaded.body.strip() != body.strip()
        or uploaded.empty_uploads
        or uploaded.assets != digests
    ):
        raise ValueError('Remote digest verification failed. Release remains a draft.')
    github.verify_candidate(revision)
    github.verify_tag(tag, revision)
    if uploaded.draft:
        github.publish(uploaded.id)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'action', choices=('inventory', 'source-run', 'authorize', 'publish')
    )
    parser.add_argument('--revision', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--run-id')
    args = parser.parse_args()
    tag = 'v' + args.version
    if args.action == 'inventory':
        print(
            json.dumps(
                archive_inventory(args.directory, args.revision, args.version), indent=2
            )
        )
        return
    github = GitHub(os.environ['GITHUB_REPOSITORY'])
    if args.action == 'authorize':
        github.verify_candidate(args.revision)
    elif args.action == 'source-run':
        run_id = source_run(
            github.release(tag), args.revision, os.environ['GITHUB_RUN_ID']
        )
        github.verify_build_run(run_id, args.revision)
        print(run_id)
    else:
        status = subprocess.check_output(
            ['python', 'scripts/versioning.py', 'status'], text=True
        )
        publish(github, tag, args.revision, args.run_id, args.directory, status)


if __name__ == '__main__':
    main()
