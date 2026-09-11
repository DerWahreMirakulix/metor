"""Public frontend host retry/cancellation tests with controlled process startup."""

# ruff: noqa: E402
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from metor.application.frontend import create_local_frontend_host
from metor.client import (
    FrontendBootstrapError,
    FrontendBootstrapReason,
    FrontendProfileCreateRequest,
    FrontendProfileSecurity,
)
from metor.data import ProfileManager, Settings, SettingKey
from metor.utils import Constants


class ClosureFrontendTests(unittest.TestCase):
    """A failed attempt is recoverable; successful start receipts prevent duplication."""

    def test_public_missing_create_cancel_transient_start_and_retry(self) -> None:
        with (
            TemporaryDirectory() as root,
            patch.object(Constants, 'DATA', Path(root) / '.metor'),
        ):
            host = create_local_frontend_host('first')
            interaction = Mock()
            with self.assertRaises(FrontendBootstrapError) as missing:
                host.bootstrap(interaction)
            self.assertEqual(
                missing.exception.reason, FrontendBootstrapReason.MISSING_PROFILE
            )
            result = host.create_profile(
                FrontendProfileCreateRequest(
                    'first', security=FrontendProfileSecurity.PLAINTEXT
                )
            )
            self.assertFalse(result.success)
            self.assertEqual(result.code, 'plaintext_profiles_disabled')
            Settings.set(SettingKey.ALLOW_PLAINTEXT_PROFILES, True)
            result = host.create_profile(
                FrontendProfileCreateRequest(
                    'first', security=FrontendProfileSecurity.PLAINTEXT
                )
            )
            self.assertTrue(result.success)
            interaction.confirm_daemon_start.return_value = None
            with self.assertRaises(FrontendBootstrapError) as cancelled:
                host.bootstrap(interaction)
            self.assertEqual(
                cancelled.exception.reason, FrontendBootstrapReason.CANCELLED
            )
            interaction.confirm_daemon_start.return_value = True
            interaction.request_session_auth_secret.side_effect = [
                'first-secret',
                'fresh-secret',
            ]
            with patch(
                'metor.application.frontend.start_managed_daemon_process',
                side_effect=[False, True],
            ) as start:
                with self.assertRaises(FrontendBootstrapError) as failed:
                    host.bootstrap(interaction)
                self.assertEqual(
                    failed.exception.reason, FrontendBootstrapReason.START_FAILED
                )
                with self.assertRaises(FrontendBootstrapError) as endpoint:
                    host.bootstrap(interaction)
                self.assertEqual(
                    endpoint.exception.reason, FrontendBootstrapReason.UNREACHABLE
                )
                self.assertEqual(start.call_count, 2)
                # A known started process with missing endpoint metadata is not
                # proof that another process may safely be launched.
                with self.assertRaises(FrontendBootstrapError) as retry:
                    host.bootstrap(interaction)
                self.assertEqual(
                    retry.exception.reason, FrontendBootstrapReason.UNREACHABLE
                )
                self.assertEqual(start.call_count, 2)
                self.assertEqual(interaction.request_session_auth_secret.call_count, 2)
                with patch.object(
                    ProfileManager, 'get_daemon_port', return_value=37412
                ):
                    attached = host.bootstrap(interaction)
                self.assertEqual(attached.port, 37412)
                self.assertIsNone(attached.session_auth.take())
                self.assertIsNone(attached.session_auth.take())

    def test_remote_forwarded_endpoint_never_launches_local_daemon(self) -> None:
        with (
            TemporaryDirectory() as root,
            patch.object(Constants, 'DATA', Path(root) / '.metor'),
        ):
            host = create_local_frontend_host('remote', True)
            result = host.create_profile(
                FrontendProfileCreateRequest('remote', remote=True, port=37413)
            )
            self.assertTrue(result.success)
            with patch(
                'metor.application.frontend.start_managed_daemon_process'
            ) as start:
                endpoint = host.bootstrap(Mock())
            self.assertEqual(endpoint.port, 37413)
            self.assertTrue(endpoint.remote)
            start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
