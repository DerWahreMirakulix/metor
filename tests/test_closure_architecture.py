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
from metor.ui.terminal.constants import Constants as TerminalConstants
from metor.utils import Constants as RuntimeConstants


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
            ('metor.client.session', 'from ..ui.gui import launch'),
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

    def test_sdk_rejects_toolkits_constant_dynamic_imports_and_lazy_exports(
        self,
    ) -> None:
        """Covers dependency spellings that an ordinary import-only scan misses."""
        cases = (
            'import kivy',
            'from sounddevice import InputStream',
            'import accesskit as accessibility',
            'import importlib\nimportlib.import_module("kivy")',
            'from importlib import import_module as load\nload("sounddevice")',
            '__import__("accesskit")',
            ('_LAZY_EXPORTS = {\n    "Gui": ("metor.ui.gui", "launch"),\n}'),
        )
        for source in cases:
            with self.subTest(source=source):
                self.assertTrue(check_source(source, 'metor.client.facade'))

    def test_sdk_allows_owned_and_standard_library_import_forms(self) -> None:
        """Prevents the negative guard from rejecting valid SDK dependencies."""
        cases = (
            'from pathlib import Path',
            'from metor.core.api import IpcEvent',
            'import importlib\nimportlib.import_module("metor.client.session")',
            (
                '_LAZY_EXPORTS = {\n'
                '    "Client": ("metor.client.session", "MetorClient"),\n'
                '}'
            ),
        )
        for source in cases:
            with self.subTest(source=source):
                self.assertEqual(check_source(source, 'metor.client.facade'), ())

    def test_security_primitives_have_one_owner_and_known_answers(self) -> None:
        self.assertIs(build_session_auth_proof_from_key, canonical_proof)
        self.assertEqual(
            canonical_proof(bytes(range(32)), bytes(range(32)).hex()),
            'e8499be4f1980d68f13222a418df5cbd97d53fddf590c2108e22d40005b70713',
        )
        self.assertEqual(
            bytes(derive_pin_verifier('2468', bytes(range(16)).hex())).hex(),
            'fc730819521b8f303b8f065360f219fc0bd4a1c8f75f95fa08ddecbe9b08d66f',
        )

    def test_terminal_defaults_have_only_the_terminal_owner(self) -> None:
        """Base runtime constants do not duplicate terminal input/rendering policy."""
        for name in ('DEFAULT_COLS', 'INPUT_SELECT_TIMEOUT_SEC', 'INPUT_SLEEP_SEC'):
            self.assertFalse(hasattr(RuntimeConstants, name), name)
            self.assertTrue(hasattr(TerminalConstants, name), name)

    def test_utils_facade_does_not_redirect_sdk_or_core_owners(self) -> None:
        """The Base facade exposes no compatibility route to shared or auth APIs."""
        import metor.utils as utils

        redirected = (
            'build_session_auth_proof',
            'build_session_auth_proof_from_key',
            'create_session_auth_salt',
            'create_session_auth_challenge',
            'derive_session_auth_proof_key',
            'verify_session_auth_proof',
            'clean_onion',
            'decode_tor_v3_onion_public_key',
            'ensure_onion_format',
            'secure_clear_buffer',
        )
        for name in redirected:
            with self.subTest(name=name):
                self.assertNotIn(name, utils.__all__)
                self.assertFalse(hasattr(utils, name))

    def test_type_caster_lazy_export_does_not_load_host_dependencies(self) -> None:
        """The retained pure input caster remains lazy and host-independent."""
        with tempfile.TemporaryDirectory() as directory:
            code = (
                'import sys; from pathlib import Path; from unittest.mock import patch; '
                f'sys.path.insert(0, {str(ROOT / "src")!r}); '
                'guard=patch.object(Path, "home", side_effect=AssertionError("host path")); guard.start(); '
                'from metor.utils import TypeCaster; assert TypeCaster.to_int("7") == 7; '
                'assert "psutil" not in sys.modules; assert "nacl" not in sys.modules; '
                'assert "metor.core" not in sys.modules; print("CASTER_INERT")'
            )
            result = subprocess.run(
                [sys.executable, '-I', '-c', code],
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'CASTER_INERT')

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
