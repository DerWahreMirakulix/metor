"""Exercise interrupted draft publication, digest verification and reviewed build inputs."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import create_autospec, patch
from zipfile import ZipFile

from scripts.release.bundle import RELEASE_VARIANTS, build_bundle_name
from scripts.release.inputs import hashed_requirements
from scripts.release.publication import (
    GitHub,
    RELEASE_PLATFORMS,
    RemoteRelease,
    archive_inventory,
    publish,
    source_run,
)


REVISION = '1' * 40
VERSION = '1.0.0'


def archives(directory: Path) -> None:
    """Supply the same candidate metadata used by both real build hosts."""
    for system in RELEASE_PLATFORMS:
        for variant in RELEASE_VARIANTS:
            name = build_bundle_name(system, 'x86_64', 3, 11, variant)
            package = {
                'sdk': 'metor-sdk',
                'base': 'metor',
                'terminal': 'metor-ui-terminal',
                'gui': 'metor-ui-gui',
            }[variant]
            metadata = json.dumps(
                {
                    'package': package,
                    'system': system,
                    'machine': 'x86_64',
                    'variant': variant,
                    'python': '3.11',
                    'abi': 'cpython-311',
                    'source_revision': REVISION,
                    'application_version': VERSION,
                }
            ).encode()
            wheel = package.replace('-', '_') + f'-{VERSION}-py3-none-any.whl'
            members = {
                part: b'test'
                for part in (
                    'install.sh',
                    'install.cmd',
                    'verify_bundle.py',
                    'INSTALL.txt',
                    'NATIVE-COMPONENTS.json',
                    f'wheelhouse/{wheel}',
                )
            }
            members['BUNDLE.json'] = metadata
            manifest = ''.join(
                hashlib.sha256(value).hexdigest() + '  ' + key + '\n'
                for key, value in members.items()
            )
            with ZipFile(directory / (name + '.zip'), 'w') as archive:
                for member, value in members.items():
                    archive.writestr(f'{name}/{member}', value)
                archive.writestr(f'{name}/SHA256SUMS.txt', manifest)


class ReleasePublicationTests(unittest.TestCase):
    def test_partial_upload_resumes_without_replacing_existing_assets(self) -> None:
        """Fail after one upload; reuse its draft, reject drift, then release exactly once."""
        with TemporaryDirectory() as temp:
            root = Path(temp)
            archives(root)
            api = create_autospec(GitHub, instance=True)
            assets: dict[str, str] = {}
            state: dict[str, str] = {}
            starters: dict[str, int] = {}

            def create(tag: str, revision: str, body: str) -> None:
                state.update(body=body, revision=revision, draft='yes')

            def read(tag: str) -> RemoteRelease | None:
                if not state:
                    return None
                return RemoteRelease(
                    1,
                    state['draft'] == 'yes',
                    state['revision'],
                    state['body'],
                    dict(assets),
                    dict(starters),
                )

            def upload(tag: str, path: Path) -> None:
                if path.name in assets:
                    raise AssertionError('Duplicated upload')
                assets[path.name] = (
                    'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()
                )
                if len(assets) == 1:
                    raise OSError('Interrupted transfer')

            api.create.side_effect = create
            api.release.side_effect = read
            api.upload.side_effect = upload
            api.publish.side_effect = lambda _id: state.update(draft='no')
            args = (api, 'v1.0.0', REVISION, '37', root, '1.0.0')
            with self.assertRaises(OSError):
                publish(*args)
            api.publish.assert_not_called()
            self.assertEqual(source_run(read('v1.0.0'), REVISION, '59'), '37')
            first = next(iter(assets))
            correct = assets[first]
            assets[first] = 'sha256:' + 'f' * 64
            with self.assertRaises(ValueError):
                publish(*args)
            api.publish.assert_not_called()
            assets[first] = correct
            starters[
                next(
                    name
                    for name in archive_inventory(root, REVISION, VERSION)
                    if name != first
                )
            ] = 57
            api.remove_empty_upload.side_effect = lambda _id: starters.clear()
            publish(*args)
            publish(*args)
            self.assertEqual(assets, archive_inventory(root, REVISION, VERSION))
            self.assertEqual(len(assets), 8)
            self.assertEqual(api.upload.call_count, 8)
            api.remove_empty_upload.assert_called_once_with(57)
            api.create.assert_called_once()
            api.publish.assert_called_once_with(1)

    def test_incorrect_candidate_partial_inventory_and_corrupt_payload_are_rejected(
        self,
    ) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp)
            archives(root)
            with self.assertRaises(ValueError):
                archive_inventory(root, '2' * 40, VERSION)
            sample = next(root.glob('*.zip'))
            with ZipFile(sample, 'a') as archive:
                archive.writestr(sample.stem + '/extra.bin', b'unlisted payload')
            with self.assertRaises(ValueError):
                archive_inventory(root, REVISION, VERSION)
            sample.unlink()
            with self.assertRaises(ValueError):
                archive_inventory(root, REVISION, VERSION)

    def test_tag_authorization_requires_current_main_ci_and_the_aggregate_job(
        self,
    ) -> None:
        github = GitHub('test/metor')
        run = {
            'id': 8,
            'head_sha': REVISION,
            'head_repository': {'full_name': 'test/metor'},
            'conclusion': 'success',
        }
        contexts = [{'jobs': [{'name': 'Required CI result', 'conclusion': 'success'}]}]
        for head, runs, jobs, allowed in (
            (REVISION, [run], contexts, True),
            ('2' * 40, [run], contexts, False),
            (REVISION, [dict(run, head_sha='3' * 40)], contexts, False),
            (REVISION, [dict(run, conclusion='failure')], contexts, False),
            (REVISION, [run], [{'jobs': []}], False),
        ):
            with (
                self.subTest(head=head, allowed=allowed),
                patch.object(
                    github,
                    '_api',
                    side_effect=[
                        {'object': {'sha': head}},
                        {'workflow_runs': runs},
                        jobs,
                    ],
                ),
            ):
                if allowed:
                    github.verify_candidate(REVISION)
                else:
                    with self.assertRaises(ValueError):
                        github.verify_candidate(REVISION)

    def test_dependency_hashes_cover_the_release_toolchain_and_new_pins_fail_closed(
        self,
    ) -> None:
        root = Path(__file__).resolve().parents[1] / 'requirements'
        hashes = hashed_requirements(
            tuple(root / name for name in ('dev.lock', 'gui.lock', 'terminal.lock')),
            include_pip=True,
        )
        for line in hashes.splitlines():
            self.assertIn(' --hash=sha256:', line)
        self.assertIn('sqlcipher3-binary==', hashes)
        with TemporaryDirectory() as temp:
            lock = Path(temp) / 'new.lock'
            lock.write_text('unreviewed==1.0.0')
            with self.assertRaises(ValueError):
                hashed_requirements((lock,))
