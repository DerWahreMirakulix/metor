"""Architecture regression tests for UI-layer boundaries and typed message DTOs."""

# ruff: noqa: E402

import importlib
import sys
import unittest
from pathlib import Path
from typing import Callable, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.core.api import (
    MessageDirectionCode,
    MessageEntry,
    MessageStatusCode,
    MessagesDataEvent,
)
from metor.ui import UIPresenter


REPO_ROOT: Path = Path(__file__).resolve().parents[1]
UI_ROOT: Path = REPO_ROOT / 'src' / 'metor' / 'ui'
APPLICATION_ROOT: Path = REPO_ROOT / 'src' / 'metor' / 'application'
LOWER_LAYER_ROOTS: tuple[Path, ...] = (
    REPO_ROOT / 'src' / 'metor' / 'core',
    REPO_ROOT / 'src' / 'metor' / 'data',
    REPO_ROOT / 'src' / 'metor' / 'utils',
)


def _collect_import_violations(
    root: Path,
    predicate: Callable[[str], bool],
) -> list[str]:
    """Collects file/line import violations for one scanned source subtree."""

    violations: list[str] = []

    for file_path in root.rglob('*.py'):
        for line_number, line in enumerate(file_path.read_text().splitlines(), 1):
            stripped: str = line.strip()
            if predicate(stripped):
                relative_path: Path = file_path.relative_to(REPO_ROOT)
                violations.append(f'{relative_path}:{line_number}: {stripped}')

    return violations


def _is_package_facade_import(line: str, package: str) -> bool:
    """Determines whether one import line targets exactly one package facade."""

    return (
        line.startswith(f'from {package} import ')
        or line == f'import {package}'
        or line.startswith(f'import {package} as ')
    )


def _is_ui_core_violation(line: str) -> bool:
    """Determines whether one UI import crosses the core boundary outside IPC API."""

    if line.startswith('from metor.core.api') or line.startswith(
        'import metor.core.api'
    ):
        return False

    return line.startswith('from metor.core') or line.startswith('import metor.core')


def _is_ui_data_violation(line: str) -> bool:
    """Determines whether one UI import crosses into forbidden data-layer modules."""

    allowed_prefixes: tuple[str, ...] = (
        'from metor.data.profile',
        'import metor.data.profile',
        'from metor.data.settings',
        'import metor.data.settings',
    )
    if line.startswith(allowed_prefixes):
        return False

    return line.startswith('from metor.data') or line.startswith('import metor.data')


def _is_ui_application_violation(line: str) -> bool:
    """Determines whether one application-layer file imports UI code."""

    return line.startswith('from metor.ui') or line.startswith('import metor.ui')


def _is_lower_layer_application_violation(line: str) -> bool:
    """Determines whether one core/data/utils file imports the application layer."""

    return line.startswith('from metor.application') or line.startswith(
        'import metor.application'
    )


def _is_application_daemon_implementation_violation(line: str) -> bool:
    """Determines whether one application import bypasses daemon package facades."""

    allowed_packages: tuple[str, ...] = (
        'metor.core.daemon',
        'metor.core.daemon.managed',
        'metor.core.daemon.headless',
    )
    if any(_is_package_facade_import(line, package) for package in allowed_packages):
        return False

    return line.startswith('from metor.core.daemon') or line.startswith(
        'import metor.core.daemon'
    )


class UiBoundaryTests(unittest.TestCase):
    def test_ui_imports_only_ipc_contracts_from_core(self) -> None:
        violations: list[str] = _collect_import_violations(
            UI_ROOT,
            _is_ui_core_violation,
        )

        self.assertEqual(violations, [])

    def test_ui_imports_only_profile_and_settings_from_data(self) -> None:
        violations: list[str] = _collect_import_violations(
            UI_ROOT,
            _is_ui_data_violation,
        )

        self.assertEqual(violations, [])

    def test_application_layer_does_not_import_ui(self) -> None:
        violations: list[str] = _collect_import_violations(
            APPLICATION_ROOT,
            _is_ui_application_violation,
        )

        self.assertEqual(violations, [])

    def test_application_imports_daemon_only_via_package_facades(self) -> None:
        violations: list[str] = _collect_import_violations(
            APPLICATION_ROOT,
            _is_application_daemon_implementation_violation,
        )

        self.assertEqual(violations, [])

    def test_lower_layers_do_not_import_application(self) -> None:
        violations: list[str] = []

        for root in LOWER_LAYER_ROOTS:
            violations.extend(
                _collect_import_violations(
                    root,
                    _is_lower_layer_application_violation,
                )
            )

        self.assertEqual(violations, [])

    def test_core_daemon_root_facade_exports_only_shared_bootstrap(self) -> None:
        daemon_package = importlib.import_module('metor.core.daemon')

        self.assertTrue(hasattr(daemon_package, 'verify_master_password'))
        self.assertTrue(hasattr(daemon_package, 'InvalidMasterPasswordError'))
        self.assertFalse(hasattr(daemon_package, 'create_managed_daemon'))
        self.assertFalse(hasattr(daemon_package, 'DaemonStatus'))
        self.assertFalse(hasattr(daemon_package, 'InvalidDaemonPasswordError'))
        self.assertFalse(hasattr(daemon_package, 'Daemon'))
        self.assertFalse(hasattr(daemon_package, 'HeadlessDaemon'))
        self.assertFalse(hasattr(daemon_package, 'build_runtime'))
        self.assertFalse(hasattr(daemon_package, 'CorruptedStorageError'))

    def test_managed_daemon_package_exports_managed_runtime_facade(self) -> None:
        managed_package = importlib.import_module('metor.core.daemon.managed')

        self.assertTrue(hasattr(managed_package, 'create_managed_daemon'))
        self.assertTrue(hasattr(managed_package, 'InvalidDaemonPasswordError'))
        self.assertTrue(hasattr(managed_package, 'CorruptedDaemonStorageError'))
        self.assertTrue(hasattr(managed_package, 'DaemonStatus'))
        self.assertFalse(hasattr(managed_package, 'Daemon'))
        self.assertFalse(hasattr(managed_package, 'build_runtime'))

    def test_shared_handlers_facade_excludes_managed_network_handler(self) -> None:
        handlers_package = importlib.import_module('metor.core.daemon.handlers')

        self.assertTrue(hasattr(handlers_package, 'DatabaseCommandHandler'))
        self.assertTrue(hasattr(handlers_package, 'SystemCommandHandler'))
        self.assertTrue(hasattr(handlers_package, 'ConfigCommandHandler'))
        self.assertFalse(hasattr(handlers_package, 'NetworkCommandHandler'))

    def test_managed_handlers_facade_exports_network_handler(self) -> None:
        handlers_package = importlib.import_module('metor.core.daemon.managed.handlers')

        self.assertTrue(hasattr(handlers_package, 'NetworkCommandHandler'))

    def test_messages_data_event_casts_entries_to_api_message_enums(self) -> None:
        event = MessagesDataEvent(
            messages=cast(
                list[MessageEntry],
                [
                    {
                        'direction': 'out',
                        'status': 'delivered',
                        'payload': 'hello',
                        'timestamp': '2026-04-04T18:30:00+00:00',
                    }
                ],
            ),
            alias='peer',
            onion='peer.onion',
        )

        message = event.messages[0]

        self.assertIs(message.direction, MessageDirectionCode.OUT)
        self.assertIs(message.status, MessageStatusCode.DELIVERED)

        rendered: str = UIPresenter.format_messages(event)

        self.assertIn('To peer:', rendered)


if __name__ == '__main__':
    unittest.main()
