"""Executable ownership, inert-import and known-answer closure regressions."""

# ruff: noqa: E402

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))

from scripts.check_boundaries import check_source, check_tree
from scripts.validate_generated_docs import validate_reproducibility
from metor.client import build_session_auth_proof_from_key, derive_pin_verifier
from metor.core.auth import build_session_auth_proof_from_key as canonical_proof
from metor.utils import build_session_auth_proof_from_key as host_proof


class ClosureArchitectureTests(unittest.TestCase):
    """Validates owner boundaries structurally and at runtime."""

    def test_all_distribution_boundaries(self) -> None:
        self.assertEqual(check_tree(ROOT / 'src'), ())

    def test_deterministic_generation_does_not_hide_stale_checked_in_files(
        self,
    ) -> None:
        path = Path('generated.json')
        with (
            patch('scripts.validate_generated_docs.GENERATED_ARTIFACT_PATHS', (path,)),
            patch('scripts.validate_generated_docs.run_generators'),
            patch(
                'scripts.validate_generated_docs.generated_artifacts',
                side_effect=[{path: b'stale'}, {path: b'current'}, {path: b'current'}],
            ),
        ):
            self.assertEqual(validate_reproducibility(), (path,))

    def test_negative_imports_include_facades_relative_aliases_and_multiline(
        self,
    ) -> None:
        cases = (
            (
                'metor.ui.terminal.launcher',
                'from metor.data import (\n ProfileManager as Innocent,\n)',
            ),
            (
                'metor.ui.terminal.launcher',
                'from ...data.profile.manager import ProfileManager as Innocent',
            ),
            ('metor.ui.terminal.launcher', 'from ..gui import launch'),
            (
                'metor.client.session',
                'from metor.application import create_local_frontend_host',
            ),
            ('metor.shared.network', 'import sqlcipher3 as storage'),
            ('metor.core.api.events', 'from metor import data as storage'),
            ('metor.cli.entry', 'from metor.ui.terminal import Theme'),
            ('metor.core.daemon.worker', 'from metor import cli'),
        )
        for module, source in cases:
            with self.subTest(module=module, source=source):
                self.assertTrue(check_source(source, module))

    def test_security_primitives_have_one_owner_and_known_answers(self) -> None:
        self.assertIs(build_session_auth_proof_from_key, canonical_proof)
        self.assertIs(host_proof, canonical_proof)
        self.assertEqual(
            canonical_proof(bytes(range(32)), bytes(range(32)).hex()),
            'e8499be4f1980d68f13222a418df5cbd97d53fddf590c2108e22d40005b70713',
        )
        self.assertEqual(
            bytes(derive_pin_verifier('2468', bytes(range(16)).hex())).hex(),
            'fc730819521b8f303b8f065360f219fc0bd4a1c8f75f95fa08ddecbe9b08d66f',
        )

    def test_sdk_import_is_inert_in_a_fresh_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            code = (
                'import sys, os; from pathlib import Path; from unittest.mock import patch; '
                f'sys.path.insert(0, {str(ROOT / "src")!r}); '
                'before=dict(os.environ); '
                'guard=patch.object(Path, "home", side_effect=AssertionError("host path lookup")); guard.start(); '
                'import metor.client, metor.core.api, metor.core.auth, metor.shared; '
                'assert "dotenv" not in sys.modules; assert "metor.data" not in sys.modules; '
                'assert not hasattr(metor.shared.Constants, "DATA"); '
                'assert dict(os.environ) == before; print("SDK_INERT")'
            )
            result = subprocess.run(
                [sys.executable, '-I', '-c', code],
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'SDK_INERT')
            self.assertEqual(os.listdir(directory), [])


if __name__ == '__main__':
    unittest.main()
