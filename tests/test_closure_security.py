"""Authenticated DTO dispatch regressions without manually minting authority."""

# ruff: noqa: E402
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import test_closure_integration as integration
from metor.client.ipc import IpcClient
from metor.core.api import (
    InitCommand,
    AuthenticateSessionCommand,
    RestrictClientCommand,
    ReauthorizeClientCommand,
    ConfigureQuickUnlockCommand,
    ClientUnlockMethod,
    QuickUnlockAction,
    EventType,
    ensure_request_id,
    IpcCommand,
    IpcEvent,
)
from metor.core.auth import (
    build_session_auth_proof,
    create_pin_verifier,
    build_pin_unlock_proof,
)
from metor.core.daemon.managed.local_auth import create_session_auth_context
from metor.utils import Constants
from metor.versioning import IPC_PROTOCOL_VERSION, IPC_PROTOCOL_MIN_SUPPORTED


class ClosureSecurityTests(unittest.TestCase):
    """Real session sockets bind full proof, restriction and purpose grants."""

    def test_full_auth_restrict_pin_none_idempotence_purpose_expiry_and_replay(
        self,
    ) -> None:
        harness = integration.ClosureDaemonTests()
        harness.setUp()
        self.addCleanup(harness.doCleanups)
        daemon = harness.daemon(
            session_auth=create_session_auth_context('test-password')
        )

        def attach() -> IpcClient:
            raw = IpcClient(
                daemon._ipc.port,
                Constants.DEFAULT_IPC_TIMEOUT,
                lambda event: None,
                lambda: None,
            )
            self.addCleanup(raw.stop)
            self.assertTrue(raw.connect())
            return raw

        def exchange(raw: IpcClient, command: IpcCommand) -> IpcEvent:
            request_id = ensure_request_id(command)
            lease = raw.begin_request(request_id)
            try:
                raw.send_command(command, lease)
                response = raw.wait_for_response(request_id, lease)
                self.assertIsNotNone(response)
                return response
            finally:
                raw.end_request(request_id, lease)

        def authenticate(raw: IpcClient, challenge: IpcEvent) -> None:
            self.assertEqual(challenge.event_type, EventType.AUTH_REQUIRED)
            proof = build_session_auth_proof(
                'test-password', challenge.challenge, challenge.salt
            )
            self.assertEqual(
                exchange(raw, AuthenticateSessionCommand(proof)).event_type,
                EventType.SESSION_AUTHENTICATED,
            )

        raw = attach()
        authenticate(
            raw,
            exchange(
                raw, InitCommand(IPC_PROTOCOL_VERSION, IPC_PROTOCOL_MIN_SUPPORTED)
            ),
        )
        salt, verifier = create_pin_verifier('2468')

        def configure() -> ConfigureQuickUnlockCommand:
            return ConfigureQuickUnlockCommand(QuickUnlockAction.SET, salt, verifier)

        authenticate(raw, exchange(raw, configure()))
        self.assertEqual(
            exchange(raw, configure()).event_type, EventType.QUICK_UNLOCK_CONFIGURED
        )

        for method in (ClientUnlockMethod.NONE, ClientUnlockMethod.PIN):
            with self.subTest(method=method):
                restricted = exchange(raw, RestrictClientCommand(unlock_method=method))
                self.assertEqual(restricted.event_type, EventType.CLIENT_RESTRICTED)
                proof = (
                    build_pin_unlock_proof(
                        '2468', restricted.salt, restricted.challenge
                    )
                    if method is ClientUnlockMethod.PIN
                    else None
                )
                self.assertEqual(
                    exchange(raw, ReauthorizeClientCommand(method, proof)).event_type,
                    EventType.CLIENT_REAUTHORIZED,
                )
                self.assertEqual(
                    exchange(raw, AuthenticateSessionCommand('00' * 32)).event_type,
                    EventType.SESSION_AUTHENTICATED,
                )
                # Idempotent acknowledgement cannot grant SET authority.
                challenge = exchange(raw, configure())
                self.assertEqual(challenge.event_type, EventType.AUTH_REQUIRED)
                authenticate(raw, challenge)
                # A valid SET grant cannot remove the PIN (wrong purpose).
                remove = exchange(
                    raw, ConfigureQuickUnlockCommand(QuickUnlockAction.REMOVE)
                )
                self.assertEqual(remove.event_type, EventType.AUTH_REQUIRED)
                # Mint an already expired grant through actual proof verification.
                challenge = exchange(raw, configure())
                with patch.object(Constants, 'SENSITIVE_AUTH_GRANT_TIMEOUT_SEC', -1.0):
                    authenticate(raw, challenge)
                self.assertEqual(
                    exchange(raw, configure()).event_type, EventType.AUTH_REQUIRED
                )
                authenticate(raw, exchange(raw, configure()))
                self.assertEqual(
                    exchange(raw, configure()).event_type,
                    EventType.QUICK_UNLOCK_CONFIGURED,
                )
                # Replaying the operation needs another purpose proof.
                self.assertEqual(
                    exchange(raw, configure()).event_type, EventType.AUTH_REQUIRED
                )
                # Complete pending auth before beginning a new restriction cycle.
                authenticate(raw, exchange(raw, configure()))
                self.assertEqual(
                    exchange(raw, configure()).event_type,
                    EventType.QUICK_UNLOCK_CONFIGURED,
                )

        other = attach()
        other_challenge = exchange(
            other, InitCommand(IPC_PROTOCOL_VERSION, IPC_PROTOCOL_MIN_SUPPORTED)
        )
        first_challenge = exchange(raw, configure())
        first_proof = build_session_auth_proof(
            'test-password', first_challenge.challenge, first_challenge.salt
        )
        self.assertEqual(
            exchange(other, AuthenticateSessionCommand(first_proof)).event_type,
            EventType.INVALID_PASSWORD,
        )
        self.assertNotEqual(first_challenge.challenge, other_challenge.challenge)


if __name__ == '__main__':
    unittest.main()
