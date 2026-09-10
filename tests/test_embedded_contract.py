"""Contract tests for the non-visual embedded preparation layer."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.client import ContactQrError, validate_contact_qr
from metor.core.api import InitEvent, IpcEvent
from metor.ui.embedded import EmbeddedPlatform, PlatformCapabilities, RevisionGate
from metor.ui.embedded.fakes import (
    FakeClock,
    FakeHardwareInput,
    FakeLocalUiSettingsStore,
    FakePrivacyLogger,
    FakeQrScanner,
)
from metor.ui.embedded.platform import (
    HardwareInputEvent,
    HardwareInputKind,
    QrScannerStatus,
)


class EmbeddedContractTests(unittest.TestCase):
    """Covers deterministic recovery and optional platform capabilities."""

    def test_revision_gate_requires_snapshot_and_rejects_duplicates(self) -> None:
        """Verifies pre-snapshot, stale, and duplicate events are rejected.

        Args:
            None

        Returns:
            None
        """
        gate = RevisionGate()
        self.assertFalse(gate.accept('event-1', 1))
        gate.install_snapshot(10)
        self.assertFalse(gate.accept('stale', 10))
        self.assertTrue(gate.accept('event-1', 11))
        self.assertFalse(gate.accept('event-1', 12))
        self.assertFalse(gate.accept('out-of-order', 9))
        gate.install_snapshot(20)
        self.assertTrue(gate.accept('event-1', 21))

    def test_init_capabilities_round_trip_over_ipc(self) -> None:
        """Verifies clients receive typed capability negotiation metadata.

        Args:
            None

        Returns:
            None
        """
        event = InitEvent(
            negotiated_version=2,
            daemon_current_version=2,
            daemon_min_supported=2,
            profile='primary',
            capabilities=['text_content', 'runtime_lock'],
        )
        decoded = IpcEvent.from_dict(json.loads(event.to_json()))
        self.assertEqual(decoded, event)

    def test_absent_optional_capabilities_have_no_ports(self) -> None:
        """Verifies unavailable hardware is represented explicitly.

        Args:
            None

        Returns:
            None
        """
        platform = EmbeddedPlatform(
            capabilities=PlatformCapabilities(),
            input=FakeHardwareInput(),
            clock=FakeClock(),
            logger=FakePrivacyLogger(),
            settings=FakeLocalUiSettingsStore(),
        )
        self.assertFalse(platform.capabilities.qr_scanner)
        self.assertIsNone(platform.qr_scanner)
        self.assertIsNone(platform.audio_capture)
        self.assertIsNone(platform.haptics)

        with self.assertRaises(ValueError):
            EmbeddedPlatform(
                capabilities=PlatformCapabilities(qr_scanner=True),
                input=FakeHardwareInput(),
                clock=FakeClock(),
                logger=FakePrivacyLogger(),
                settings=FakeLocalUiSettingsStore(),
            )

    def test_input_and_clock_fakes_are_deterministic(self) -> None:
        """Verifies hardware event and timer tests need no device runtime.

        Args:
            None

        Returns:
            None
        """
        source = FakeHardwareInput()
        events: list[HardwareInputEvent] = []
        source.subscribe(events.append)
        source.emit(HardwareInputEvent(HardwareInputKind.PTT_PRESS))
        self.assertEqual(events[0].kind, HardwareInputKind.PTT_PRESS)
        clock = FakeClock(100.0)
        clock.advance(2.5)
        self.assertEqual(clock.monotonic(), 2.5)
        self.assertEqual(clock.wall_time(), 102.5)

    def test_settings_and_logs_reject_cross_boundary_data(self) -> None:
        """Verifies local settings scope and payload-free diagnostics.

        Args:
            None

        Returns:
            None
        """
        settings = FakeLocalUiSettingsStore()
        settings.set('ui.embedded.brightness', 50)
        with self.assertRaises(ValueError):
            settings.set('daemon.fallback_to_drop', True)
        logger = FakePrivacyLogger()
        logger.log('ipc.reconnected', {'attempt': 2})
        with self.assertRaises(ValueError):
            logger.log('message.received', {'text': 'secret'})

    def test_contact_qr_parser_returns_stable_validation_codes(self) -> None:
        """Verifies scanner output is validated by the SDK, not the platform.

        Args:
            None

        Returns:
            None
        """
        malformed = validate_contact_qr(b'not-json')
        unsupported = validate_contact_qr('{"version":2,"onion":"x"}')
        unknown_fields = validate_contact_qr(
            '{"version":1,"onion":"x","secret":"unexpected"}'
        )
        self.assertIs(malformed.error, ContactQrError.MALFORMED)
        self.assertIs(unsupported.error, ContactQrError.UNSUPPORTED_VERSION)
        self.assertIs(unknown_fields.error, ContactQrError.INVALID_FIELDS)
        valid = validate_contact_qr(
            '{"version":1,"onion":'
            '"gqncaw2sjprzovtdquir4etnswg2eyvomid4bsbdld2p5roay5vmvtyd.onion",'
            '"alias":"Alice"}'
        )
        self.assertTrue(valid.valid)
        self.assertEqual(valid.payload.alias if valid.payload else None, 'Alice')

    def test_qr_fake_exposes_permission_state(self) -> None:
        """Verifies permission absence disables scanning until requested.

        Args:
            None

        Returns:
            None
        """
        scanner = FakeQrScanner(b'payload', permission_granted=False)
        self.assertIs(scanner.status(), QrScannerStatus.PERMISSION_REQUIRED)
        with self.assertRaises(PermissionError):
            scanner.scan()
        self.assertTrue(scanner.request_permission())
        self.assertIs(scanner.status(), QrScannerStatus.READY)
        self.assertEqual(scanner.scan(), b'payload')


if __name__ == '__main__':
    unittest.main()
