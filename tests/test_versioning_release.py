"""Tests for central versioning, database generations, and release gates."""

# ruff: noqa: E402

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metor.data.profile.config import Config
from metor.client import MetorClient
from metor.core.api import InitCommand, InitEvent
from metor.core.daemon.managed.network.handshake import HandshakeProtocol
from metor.data.sql import (
    LegacyDatabaseSchemaError,
    NewerDatabaseSchemaError,
    SqlManager,
)
from metor.data.sql.backends import SqlCipherCursor, sqlite3
from metor.data.sql.migrations import SchemaMigration, migrate_schema
from metor.data.sql.schema import initialize_database
from metor.utils.constants import Constants
from metor.versioning import (
    APP_VERSION,
    BLOB_FORMAT_MIN_SUPPORTED,
    BLOB_FORMAT_VERSION,
    DB_SCHEMA_VERSION,
    IPC_PROTOCOL_VERSION,
    IPC_PROTOCOL_MIN_SUPPORTED,
    KEYSLOT_FORMAT_MIN_SUPPORTED,
    KEYSLOT_FORMAT_VERSION,
    PEER_PROTOCOL_MIN_SUPPORTED,
    PEER_PROTOCOL_VERSION,
    negotiate_protocol_generation,
    validate_version_registry,
)
from scripts.release.compatibility import compare_manifests, ipc_breaking_changes
from scripts.release.paths import (
    API_DOC_PATH,
    API_SCHEMA_PATH,
    COMPATIBILITY_MANIFEST_PATH,
    GENERATED_DOCS_DIR,
    SETTINGS_DOC_PATH,
)
from scripts.release.semver import calculate_next_version, select_latest_stable_release
from scripts.validate_wheel_versions import validate_wheel_versions


class _FakeConfig:
    """Minimal SQL configuration for isolated schema tests."""

    def get_bool(self, _key: object) -> bool:
        """Disables optional SQL logging and runtime mirrors.

        Args:
            _key (object): Ignored setting identifier.

        Returns:
            bool: Always false.
        """
        return False


def _ipc_schema(
    properties: dict[str, dict[str, object]],
    required: list[str] | None = None,
) -> dict[str, object]:
    """Builds a compact generated-schema fixture with one command.

    Args:
        properties (dict[str, dict[str, object]]): DTO property schemas.
        required (list[str] | None): Required DTO fields.

    Returns:
        dict[str, object]: Generated-schema shaped fixture.
    """
    dto: dict[str, object] = {
        'type': 'object',
        'properties': properties,
    }
    if required:
        dto['required'] = required
    return {
        'definitions': {'ExampleCommand': dto},
        'commands': {'example': {'$ref': '#/definitions/ExampleCommand'}},
        'events': {},
    }


def _release_manifest(ipc_schema: dict[str, object]) -> dict[str, object]:
    """Builds a compact compatibility-manifest fixture.

    Args:
        ipc_schema (dict[str, object]): Generated IPC schema fixture.

    Returns:
        dict[str, object]: Candidate compatibility manifest.
    """
    return {
        'ipc': {'current': 2, 'minimum_supported': 2, 'schema': ipc_schema},
        'peer': {
            'current': 1,
            'minimum_supported': 1,
            'contract': {'frame': 'v1'},
        },
        'database': {
            'current': 1,
            'minimum_supported': 1,
            'schema': {'tables': []},
        },
        'keyslot': {
            'current': 1,
            'minimum_supported': 1,
            'contract': {'fields': ['version']},
        },
        'blob': {
            'current': 1,
            'minimum_supported': 1,
            'contract': {'framing': 'v1'},
        },
        'derivation': {
            'profile_key': {'current': 1, 'context': 'v1'},
            'blob_object': {'current': 1, 'context': 'v1'},
        },
    }


class VersionRegistryTests(unittest.TestCase):
    """Covers the authoritative registry and packaging source of truth."""

    def test_registry_invariants_and_storage_reader_claims_are_valid(self) -> None:
        """Verifies central versions and exact storage-reader support.

        Args:
            None

        Returns:
            None
        """
        self.assertEqual(validate_version_registry(), ())
        self.assertEqual(KEYSLOT_FORMAT_MIN_SUPPORTED, KEYSLOT_FORMAT_VERSION)
        self.assertEqual(BLOB_FORMAT_MIN_SUPPORTED, BLOB_FORMAT_VERSION)

    def test_generic_constants_no_longer_owns_protocol_versions(self) -> None:
        """Verifies protocol versions left the generic Constants class.

        Args:
            None

        Returns:
            None
        """
        self.assertFalse(hasattr(Constants, 'IPC_PROTOCOL_VERSION'))
        self.assertFalse(hasattr(Constants, 'PEER_PROTOCOL_VERSION'))

    def test_all_distributions_use_dynamic_central_application_version(self) -> None:
        """Verifies package metadata has no second static application version.

        Args:
            None

        Returns:
            None
        """
        root: Path = Path(__file__).resolve().parents[1]
        for relative_path in (
            'pyproject.toml',
            'packaging/daemon/pyproject.toml',
            'packaging/sdk/pyproject.toml',
        ):
            content: str = (root / relative_path).read_text(encoding='utf-8')
            self.assertRegex(content, r'dynamic = \[[^\]]*"version"[^\]]*\]')
            self.assertIn('metor.versioning.APP_VERSION', content)
            self.assertNotIn(f'version = "{APP_VERSION}"', content)

    def test_compatibility_assignments_exist_only_in_registry(self) -> None:
        """Verifies production modules do not duplicate authoritative values.

        Args:
            None

        Returns:
            None
        """
        root: Path = Path(__file__).resolve().parents[1]
        names: tuple[str, ...] = (
            'IPC_PROTOCOL_VERSION',
            'PEER_PROTOCOL_VERSION',
            'DB_SCHEMA_VERSION',
            'KEYSLOT_FORMAT_VERSION',
            'BLOB_FORMAT_VERSION',
        )
        for name in names:
            owners: list[Path] = []
            pattern = re.compile(rf'^{name}: int = \d+$', re.MULTILINE)
            for source_path in (root / 'src').rglob('*.py'):
                if pattern.search(source_path.read_text(encoding='utf-8')):
                    owners.append(source_path.relative_to(root))
            self.assertEqual(owners, [Path('src/metor/versioning.py')])


class ProtocolNegotiationTests(unittest.TestCase):
    """Covers inclusive IPC and peer protocol-range intersection."""

    def test_range_matrix_selects_highest_overlap_or_rejects(self) -> None:
        """Verifies current/minimum semantics in both negotiation directions.

        Args:
            None

        Returns:
            None
        """
        cases: tuple[tuple[int, int, int, int, int | None], ...] = (
            (2, 2, 2, 2, 2),
            (3, 2, 2, 2, 2),
            (3, 2, 3, 2, 3),
            (3, 3, 2, 2, None),
            (1, 1, 2, 2, None),
        )
        for (
            local_current,
            local_minimum,
            remote_current,
            remote_minimum,
            expected,
        ) in cases:
            with self.subTest(
                local=(local_minimum, local_current),
                remote=(remote_minimum, remote_current),
            ):
                self.assertEqual(
                    negotiate_protocol_generation(
                        local_current,
                        local_minimum,
                        remote_current,
                        remote_minimum,
                    ),
                    expected,
                )
                self.assertEqual(
                    negotiate_protocol_generation(
                        remote_current,
                        remote_minimum,
                        local_current,
                        local_minimum,
                    ),
                    expected,
                )

    def test_ipc_dtos_advertise_ranges_and_client_validates_selection(self) -> None:
        """Verifies explicit IPC range fields and negotiated-generation checks.

        Args:
            None

        Returns:
            None
        """
        command = InitCommand(
            current_version=IPC_PROTOCOL_VERSION,
            min_supported=IPC_PROTOCOL_MIN_SUPPORTED,
        )
        self.assertEqual(command.current_version, IPC_PROTOCOL_VERSION)
        self.assertEqual(command.min_supported, IPC_PROTOCOL_MIN_SUPPORTED)
        accepted = InitEvent(
            negotiated_version=IPC_PROTOCOL_VERSION,
            daemon_current_version=IPC_PROTOCOL_VERSION,
            daemon_min_supported=IPC_PROTOCOL_MIN_SUPPORTED,
        )
        future_only = InitEvent(
            negotiated_version=IPC_PROTOCOL_VERSION + 1,
            daemon_current_version=IPC_PROTOCOL_VERSION + 1,
            daemon_min_supported=IPC_PROTOCOL_VERSION + 1,
        )
        self.assertTrue(MetorClient._accepts_init_event(accepted))
        self.assertFalse(MetorClient._accepts_init_event(future_only))

    def test_peer_frames_exchange_both_range_endpoints(self) -> None:
        """Verifies challenge and auth frames advertise the complete peer range.

        Args:
            None

        Returns:
            None
        """
        challenge: str = 'ab' * Constants.TOR_HANDSHAKE_CHALLENGE_BYTES
        self.assertEqual(
            HandshakeProtocol.parse_challenge_line(
                HandshakeProtocol.build_challenge_line(challenge)
            ),
            (challenge, PEER_PROTOCOL_VERSION, PEER_PROTOCOL_MIN_SUPPORTED),
        )
        auth = HandshakeProtocol.parse_auth_line(
            HandshakeProtocol.build_auth_line('peer', 'signature')
        )
        self.assertEqual(
            auth,
            (
                'peer',
                'signature',
                PEER_PROTOCOL_VERSION,
                PEER_PROTOCOL_MIN_SUPPORTED,
                False,
                False,
            ),
        )


class DatabaseVersionTests(unittest.TestCase):
    """Covers schema initialization, validation, and migration atomicity."""

    def _manager(self, path: Path, key: bytes | None = None) -> SqlManager:
        """Creates an isolated SQL manager.

        Args:
            path (Path): Database file path.
            key (bytes | None): Optional SQLCipher key.

        Returns:
            SqlManager: Initialized manager.
        """
        return SqlManager(path, cast(Config, _FakeConfig()), key)

    def test_new_plaintext_and_encrypted_databases_receive_current_version(
        self,
    ) -> None:
        """Verifies both database modes persist the central schema generation.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            root: Path = Path(temp_dir)
            for name, key in (('plain.db', None), ('encrypted.db', b'k' * 32)):
                path: Path = root / name
                manager: SqlManager = self._manager(path, key)
                self.assertEqual(
                    manager.fetchall('PRAGMA user_version'), [(DB_SCHEMA_VERSION,)]
                )
                SqlManager.close_connection(path)

    def test_current_opens_and_future_or_populated_zero_reject(self) -> None:
        """Verifies deterministic handling of current, future, and legacy schemas.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            root: Path = Path(temp_dir)
            current_path: Path = root / 'current.db'
            self._manager(current_path)
            SqlManager.close_connection(current_path)
            self._manager(current_path)
            SqlManager.close_connection(current_path)

            future_path: Path = root / 'future.db'
            connection = sqlite3.connect(str(future_path))
            with connection:
                initialize_database(connection)
                connection.execute(f'PRAGMA user_version = {DB_SCHEMA_VERSION + 1}')
            connection.close()
            with self.assertRaises(NewerDatabaseSchemaError):
                self._manager(future_path)

            zero_path: Path = root / 'zero.db'
            connection = sqlite3.connect(str(zero_path))
            with connection:
                connection.execute('CREATE TABLE old_development_data (value TEXT)')
            connection.close()
            with self.assertRaises(LegacyDatabaseSchemaError):
                self._manager(zero_path)

    def test_failed_initialization_does_not_stamp_schema_version(self) -> None:
        """Verifies a failed schema transaction remains at version zero.

        Args:
            None

        Returns:
            None
        """
        connection = sqlite3.connect(':memory:')

        def fail_creation(cursor: SqlCipherCursor) -> None:
            """Raises during the patched schema creation step.

            Args:
                cursor (SqlCipherCursor): Active test cursor.

            Returns:
                None
            """
            cursor.execute('CREATE TABLE should_rollback (value TEXT)')
            raise RuntimeError('schema failure')

        with (
            patch('metor.data.sql.schema.create_core_schema', fail_creation),
            self.assertRaises(RuntimeError),
        ):
            initialize_database(connection)
        self.assertEqual(connection.execute('PRAGMA user_version').fetchone(), (0,))
        self.assertIsNone(
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'should_rollback'"
            ).fetchone()
        )
        connection.close()

    def test_failed_migration_rolls_back_ddl_and_version(self) -> None:
        """Verifies a failed migration cannot falsely advance user_version.

        Args:
            None

        Returns:
            None
        """
        connection = sqlite3.connect(':memory:')
        connection.execute('PRAGMA user_version = 1')
        connection.commit()

        def fail_step(cursor: SqlCipherCursor) -> None:
            """Mutates and then fails inside one migration transaction.

            Args:
                cursor (SqlCipherCursor): Active migration cursor.

            Returns:
                None
            """
            cursor.execute('CREATE TABLE should_rollback (value TEXT)')
            raise RuntimeError('migration failure')

        step = SchemaMigration(1, 2, fail_step)
        with (
            patch('metor.data.sql.migrations.migration_path', return_value=(step,)),
            self.assertRaises(ValueError),
        ):
            migrate_schema(connection, 1)
        self.assertEqual(connection.execute('PRAGMA user_version').fetchone(), (1,))
        self.assertIsNone(
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'should_rollback'"
            ).fetchone()
        )
        connection.close()

    def test_successful_migration_advances_version_after_step(self) -> None:
        """Verifies a completed migration durably advances user_version.

        Args:
            None

        Returns:
            None
        """
        connection = sqlite3.connect(':memory:')
        connection.execute('PRAGMA user_version = 1')
        connection.commit()

        def apply_step(cursor: SqlCipherCursor) -> None:
            """Creates the schema object for a successful migration.

            Args:
                cursor (SqlCipherCursor): Active migration cursor.

            Returns:
                None
            """
            cursor.execute('CREATE TABLE migrated (value TEXT)')

        step = SchemaMigration(1, 2, apply_step)
        with patch('metor.data.sql.migrations.migration_path', return_value=(step,)):
            migrate_schema(connection, 1)
        self.assertEqual(connection.execute('PRAGMA user_version').fetchone(), (2,))
        self.assertEqual(
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'migrated'"
            ).fetchone(),
            ('migrated',),
        )
        connection.close()


class ReleaseCompatibilityTests(unittest.TestCase):
    """Covers SemVer and release compatibility decisions."""

    def test_semver_release_calculation(self) -> None:
        """Verifies first, patch, minor, major, and prerelease calculations.

        Args:
            None

        Returns:
            None
        """
        self.assertEqual(calculate_next_version('0.2.0', 'current'), '0.2.0')
        self.assertEqual(
            calculate_next_version('0.2.0', 'patch', previous_release='v0.2.0'),
            '0.2.1',
        )
        self.assertEqual(
            calculate_next_version('0.2.0', 'minor', previous_release='v0.2.0'),
            '0.3.0',
        )
        self.assertEqual(
            calculate_next_version('0.2.0', 'major', previous_release='v0.2.0'),
            '1.0.0',
        )
        self.assertEqual(
            calculate_next_version('0.2.0', 'minor', 'rc', 'v0.2.0'),
            '0.3.0-rc.1',
        )
        self.assertEqual(
            calculate_next_version('0.3.0-rc.1', 'minor', 'rc', 'v0.3.0-rc.1'),
            '0.3.0-rc.2',
        )
        self.assertEqual(
            calculate_next_version('0.3.0-rc.2', 'minor', 'none', 'v0.3.0-rc.2'),
            '0.3.0',
        )

    def test_release_baseline_uses_highest_stable_semver(self) -> None:
        """Verifies release publication order cannot select an older backport.

        Args:
            None

        Returns:
            None
        """
        self.assertEqual(
            select_latest_stable_release(
                ('v0.4.3', 'v0.5.0', 'v0.6.0-rc.1', 'not-a-release')
            ),
            'v0.5.0',
        )
        self.assertIsNone(select_latest_stable_release(('v0.6.0-beta.1',)))

    def test_ipc_addition_is_compatible_without_protocol_bump(self) -> None:
        """Verifies an optional field remains additive.

        Args:
            None

        Returns:
            None
        """
        old = _ipc_schema({'value': {'type': 'string'}}, ['value'])
        new = _ipc_schema(
            {'value': {'type': 'string'}, 'optional': {'type': 'integer'}}, ['value']
        )
        self.assertEqual(ipc_breaking_changes(old, new), ())
        report = compare_manifests(_release_manifest(old), _release_manifest(new))
        self.assertEqual(report.errors, ())

    def test_breaking_ipc_requires_and_accepts_explicit_bump(self) -> None:
        """Verifies required additions fail without but pass with an IPC bump.

        Args:
            None

        Returns:
            None
        """
        old = _ipc_schema({'value': {'type': 'string'}}, ['value'])
        new = _ipc_schema(
            {'value': {'type': 'string'}, 'required_new': {'type': 'integer'}},
            ['value', 'required_new'],
        )
        previous = _release_manifest(old)
        current = _release_manifest(new)
        self.assertTrue(compare_manifests(previous, current).errors)
        cast(dict[str, object], current['ipc'])['current'] = IPC_PROTOCOL_VERSION + 1
        self.assertEqual(compare_manifests(previous, current).errors, ())

    def test_ipc_checker_detects_route_field_type_and_enum_breaks(self) -> None:
        """Verifies deterministic IPC breaking-change classifications.

        Args:
            None

        Returns:
            None
        """
        old = _ipc_schema(
            {
                'kept': {'type': 'string'},
                'removed': {'type': 'integer'},
                'choice': {'type': 'string', 'enum': ['a', 'b']},
            },
            ['kept'],
        )
        removed_route = {'definitions': {}, 'commands': {}, 'events': {}}
        self.assertIn(
            'IPC command removed: example', ipc_breaking_changes(old, removed_route)
        )

        changed = _ipc_schema(
            {
                'kept': {'type': 'integer'},
                'choice': {'type': 'string', 'enum': ['a']},
                'required_new': {'type': 'boolean'},
            },
            ['kept', 'required_new'],
        )
        changes = ipc_breaking_changes(old, changed)
        self.assertIn('IPC field removed: example.removed', changes)
        self.assertIn('IPC required field added: example.required_new', changes)
        self.assertIn('IPC field type narrowed: example.kept', changes)
        self.assertIn('IPC field type narrowed: example.choice', changes)

    def test_first_release_establishes_baseline_without_automatic_bumps(self) -> None:
        """Verifies no-history validation preserves every explicit generation.

        Args:
            None

        Returns:
            None
        """
        manifest = _release_manifest(_ipc_schema({'value': {'type': 'string'}}))
        before: str = json.dumps(manifest, sort_keys=True)
        report = compare_manifests(None, manifest)
        self.assertEqual(report.errors, ())
        self.assertIn('baseline', report.notes[0])
        self.assertEqual(json.dumps(manifest, sort_keys=True), before)

    def test_invalid_minimum_and_unversioned_database_change_block_release(
        self,
    ) -> None:
        """Verifies minimum and persistent-schema gates fail closed.

        Args:
            None

        Returns:
            None
        """
        schema = _ipc_schema({'value': {'type': 'string'}})
        previous = _release_manifest(schema)
        current = _release_manifest(schema)
        cast(dict[str, object], current['database'])['schema'] = {
            'tables': [{'name': 'new_table'}]
        }
        cast(dict[str, object], current['peer'])['minimum_supported'] = 2
        report = compare_manifests(previous, current)
        self.assertTrue(any('minimum supported exceeds' in e for e in report.errors))
        self.assertTrue(any('SQL schema changed' in e for e in report.errors))

    def test_peer_contract_change_requires_explicit_classification(self) -> None:
        """Verifies peer semantic review cannot be inferred from a source diff.

        Args:
            None

        Returns:
            None
        """
        schema = _ipc_schema({'value': {'type': 'string'}})
        previous = _release_manifest(schema)
        current = _release_manifest(schema)
        cast(dict[str, object], current['peer'])['contract'] = {'frame': 'expanded'}
        self.assertTrue(compare_manifests(previous, current).errors)
        self.assertEqual(
            compare_manifests(previous, current, 'additive').errors,
            (),
        )

    def test_all_built_wheels_report_central_application_version(self) -> None:
        """Builds and validates the full, daemon, and SDK wheel metadata.

        Args:
            None

        Returns:
            None
        """
        root: Path = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as temp_dir:
            wheel_dir: Path = Path(temp_dir)
            for source in (
                root,
                root / 'packaging' / 'daemon',
                root / 'packaging' / 'sdk',
            ):
                subprocess.run(
                    [
                        sys.executable,
                        '-m',
                        'pip',
                        'wheel',
                        '--no-deps',
                        '--no-build-isolation',
                        str(source),
                        '-w',
                        str(wheel_dir),
                    ],
                    cwd=root,
                    check=True,
                    stdout=subprocess.DEVNULL,
                )
            self.assertEqual(
                validate_wheel_versions(tuple(wheel_dir.glob('*.whl'))), ()
            )
            for wheel_path in wheel_dir.glob('*.whl'):
                with ZipFile(wheel_path) as archive:
                    self.assertIn('metor/versioning.py', archive.namelist())
                    if wheel_path.name.startswith('metor_daemon-'):
                        metadata_name: str = next(
                            name
                            for name in archive.namelist()
                            if name.endswith('.dist-info/METADATA')
                        )
                        metadata: str = archive.read(metadata_name).decode('utf-8')
                        self.assertIn(
                            f'Requires-Dist: metor-sdk=={APP_VERSION}', metadata
                        )

    def test_wheel_validator_requires_all_variants(self) -> None:
        """Verifies package validation rejects an incomplete release wheel set.

        Args:
            None

        Returns:
            None
        """
        self.assertTrue(validate_wheel_versions(()))


class DocumentationReleaseArchitectureTests(unittest.TestCase):
    """Covers canonical generated paths and dry-run workflow isolation."""

    def test_generated_artifacts_have_one_canonical_location(self) -> None:
        """Verifies generated references live only in their ownership directory.

        Args:
            None

        Returns:
            None
        """
        root: Path = Path(__file__).resolve().parents[1]
        self.assertEqual(GENERATED_DOCS_DIR, root / 'docs' / 'generated')
        for path in (
            API_DOC_PATH,
            SETTINGS_DOC_PATH,
            API_SCHEMA_PATH,
            COMPATIBILITY_MANIFEST_PATH,
        ):
            self.assertTrue(path.is_file())
        for stale_name in (
            'API.md',
            'SETTINGS.md',
            'api.schema.json',
            'compatibility.json',
        ):
            self.assertFalse((root / 'docs' / stale_name).exists())
        self.assertFalse((root / 'docs' / 'README.md').exists())
        for generated_markdown in (API_DOC_PATH, SETTINGS_DOC_PATH):
            self.assertTrue(
                generated_markdown.read_text(encoding='utf-8').startswith(
                    '<!-- GENERATED FILE. DO NOT EDIT MANUALLY. -->'
                )
            )

    def test_release_dry_run_cannot_reach_repository_mutations(self) -> None:
        """Verifies commits, tags, pushes, and releases are publish-job-only.

        Args:
            None

        Returns:
            None
        """
        root: Path = Path(__file__).resolve().parents[1]
        workflow: str = (root / '.github' / 'workflows' / 'release.yml').read_text(
            encoding='utf-8'
        )
        validation_jobs: str = workflow.split('\n  publish:', maxsplit=1)[0]
        self.assertNotIn('git commit ', validation_jobs)
        self.assertNotIn('git tag ', validation_jobs)
        self.assertNotIn('git push ', validation_jobs)
        self.assertNotIn('gh release create ', validation_jobs)
        self.assertIn('if: inputs.dry_run == false', workflow)

    def test_release_workflow_scopes_writes_and_generates_all_artifacts(
        self,
    ) -> None:
        """Verifies publishing guards and generated-document release inputs.

        Args:
            None

        Returns:
            None
        """
        root: Path = Path(__file__).resolve().parents[1]
        workflow: str = (root / '.github' / 'workflows' / 'release.yml').read_text(
            encoding='utf-8'
        )
        validation_jobs, publish_job = workflow.split('\n  publish:', maxsplit=1)
        self.assertNotIn('\npermissions:\n  contents: write', workflow)
        self.assertIn('Reject non-main publish requests', validation_jobs)
        self.assertIn("$GITHUB_REF_NAME\" != 'main'", validation_jobs)
        self.assertIn('contents: read', validation_jobs)
        self.assertIn('contents: write', publish_job)
        self.assertIn("github.ref_name == 'main'", publish_job)
        self.assertIn('actions/setup-node@v6', validation_jobs)
        self.assertIn('node-version: "22.17.1"', validation_jobs)
        self.assertIn('npm ci', validation_jobs)
        self.assertIn('python scripts/validate_generated_docs.py', validation_jobs)
        self.assertIn('docs/generated/SETTINGS.md', workflow)
        self.assertIn('if ! git diff --cached --quiet; then', publish_job)
        self.assertIn('--select-baseline', validation_jobs)

    def test_generated_docs_workflow_uses_canonical_allowlist(self) -> None:
        """Verifies generated-document automation cannot stage authored docs.

        Args:
            None

        Returns:
            None
        """
        root: Path = Path(__file__).resolve().parents[1]
        workflow: str = (
            root / '.github' / 'workflows' / 'generate_api_docs.yml'
        ).read_text(encoding='utf-8')
        self.assertIn('python scripts/validate_generated_docs.py', workflow)
        self.assertIn('"scripts/validate_generated_docs.py"', workflow)
        self.assertIn(
            'git add docs/generated/API.md docs/generated/SETTINGS.md '
            'docs/generated/api.schema.json docs/generated/compatibility.json',
            workflow,
        )
        self.assertIn('if ! git diff --cached --quiet; then', workflow)


if __name__ == '__main__':
    unittest.main()
