"""GUI vertical-slice tests at configuration, launcher and worker boundaries."""

from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from metor.client import FrontendProfileState
from metor.client import (
    FrontendLaunchContext,
    OneUseSecretProvider,
    build_session_auth_proof,
)
from metor.cli.parser import CliParser
from metor.core.api import (
    Delivery,
    DropQueuedEvent,
    RuntimeSnapshotEvent,
    MessageDirectionCode,
    VoiceDataEvent,
    TextAcceptedEvent,
    MessageOutcomeEvent,
    MessageStatusCode,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.launcher import launch
from metor.ui.gui.platform import DeviceConfigurationError, read_configuration
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.runtime.interaction import Interactions
from metor.ui.gui.state import GuiState, Route
from metor.ui.gui.state.mailbox import Mailbox, Update
from metor.ui.gui.state.notifications import NoticeKind
from metor.utils import open_private_binary_file


DEVICE = """schema_version = 1
[display]
adapter = "simulator"
width_px = 960
height_px = 1600
scale = 2
[input]
adapter = "simulator"
ptt_binding = "ptt"
power_binding = "power"
touch = true
"""


def _write_private_configuration(path: Path, content: str) -> None:
    """Writes one configuration through the production private-file owner.

    Args:
        path (Path): Exact temporary configuration path.
        content (str): UTF-8 TOML fixture content.

    Returns:
        None
    """
    with open_private_binary_file(path) as handle:
        handle.write(content.encode('utf-8'))


class ConfigurationTests(unittest.TestCase):
    """Checks explicit mode resolution and side-effect-free schema rejection."""

    def test_no_file_is_desktop_not_simulation(self) -> None:
        """No config means desktop; simulation needs its explicit flag."""
        self.assertEqual(read_configuration(None, False).mode, 'desktop')
        self.assertEqual(read_configuration(None, True).mode, 'simulator')

    def test_density_rotation_and_required_physical_failure(self) -> None:
        """A simulator description never becomes a real physical driver."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'device.toml'
            _write_private_configuration(path, DEVICE)
            self.assertEqual(
                read_configuration(str(path), True).logical_size, (480, 800)
            )
            with self.assertRaises(DeviceConfigurationError):
                read_configuration(str(path), False)
            _write_private_configuration(
                path,
                DEVICE.replace('width_px = 960', 'width_px = 1600').replace(
                    'height_px = 1600', 'height_px = 960'
                )
                + '\n',
            )
            with self.assertRaises(DeviceConfigurationError):
                read_configuration(str(path), True)

    def test_strict_types_unknown_fields_bindings_and_bounds(self) -> None:
        """Unsafe input rejects before adapter or host activation."""
        variants = [
            DEVICE.replace('schema_version = 1', 'schema_version = true'),
            DEVICE.replace('scale = 2', 'scale = nan'),
            DEVICE.replace('width_px = 960', 'width_px = -1'),
            DEVICE.replace('scale = 2', 'scale = 8'),
            DEVICE.replace('power_binding = "power"', 'power_binding = "ptt"'),
            DEVICE.replace('adapter = "simulator"', 'adapter = "os.system"'),
            DEVICE + '\n[drivers.evil]\ncommand="shutdown now"',
            DEVICE + '\n[clipboard]\npolicy="system"',
            DEVICE + '\n[profile]\npassword="secret"',
            DEVICE + '\n[audio]\nadapter="fake"',
            DEVICE + '\n[input]\n',
            '#' * (GuiLimits.DEVICE_BYTES + 1),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'device.toml'
            for content in variants:
                with self.subTest(content=content[:50]):
                    _write_private_configuration(path, content)
                    with self.assertRaises(DeviceConfigurationError):
                        read_configuration(str(path), True)

    def test_invalid_launch_never_calls_host(self) -> None:
        """The selected provider validates before graphical bootstrap."""
        host = Mock()
        context = FrontendLaunchContext(
            'test', host, device_config='/missing/metor-device.toml'
        )
        with patch('sys.stderr'):
            self.assertEqual(launch(context), 2)
        self.assertEqual(host.mock_calls, [])

    def test_help_parser_retains_gui_options_without_loading_gui(self) -> None:
        """Common parsing owns options and help independently of Kivy."""
        args, extra = CliParser.parse(
            [
                'chat',
                '--ui',
                'gui',
                '--simulator',
                '--device-config',
                'device.toml',
                '--help',
            ]
        )
        self.assertTrue(args.chat_help)
        self.assertTrue(args.simulator)
        self.assertEqual(args.device_config, 'device.toml')
        self.assertEqual(extra, [])


class PresentationTests(unittest.TestCase):
    """Exercises public enclosing routing and bounded state behavior."""

    def test_master_navigation_returns_to_neutral_root_without_replaying_details(
        self,
    ) -> None:
        """A master selection replaces stale detail history while child views retain Back.

        Args:
            None
        Returns:
            None
        """
        state = GuiState()
        state.route = Route('V08', 'first-peer', Delivery.DROP)
        state.navigate(Route('V12'), from_root=True)
        self.assertEqual(state.back_stack, [Route('V06')])
        state.back()
        self.assertEqual(state.route, Route('V06'))

        state.root_delivery = Delivery.LIVE
        state.navigate(Route('V11', delivery=Delivery.LIVE), from_root=True)
        state.navigate(Route('V13'))
        state.back()
        self.assertEqual(state.route, Route('V11', delivery=Delivery.LIVE))
        state.back()
        self.assertEqual(state.route, Route('V07', delivery=Delivery.LIVE))

        state.navigate(Route('V16'), from_root=True)
        state.navigate(Route('V17'), from_root=True)
        state.back()
        self.assertEqual(state.route, Route('V07', delivery=Delivery.LIVE))

        state.select_root_delivery(Delivery.DROP)
        self.assertEqual(state.route, Route('V06'))
        state.navigate(Route('V12'), from_root=True)
        state.select_root_delivery(Delivery.LIVE)
        self.assertEqual(state.route, Route('V12'))
        state.back()
        self.assertEqual(state.route, Route('V07', delivery=Delivery.LIVE))

    def test_back_cancels_list_selection_before_leaving_view(self) -> None:
        """Visible and hardware Back share contact and notification selection semantics.

        Args:
            None
        Returns:
            None
        """
        controller = GuiController(
            FrontendLaunchContext(
                'fixture',
                Mock(
                    profile_state=lambda: FrontendProfileState(
                        'fixture', True, False, False
                    )
                ),
            )
        )
        controller.state.covered = False
        controller.state.route = Route('V12')
        controller.contacts.book.selecting = True
        controller.contacts.book.selected.add('peer')
        controller.back()
        self.assertEqual(controller.state.route, Route('V12'))
        self.assertFalse(controller.contacts.book.selecting)
        self.assertFalse(controller.contacts.book.selected)

        controller.state.route = Route('V16')
        controller.notifications.store.selecting = True
        controller.notifications.store.selected.add((NoticeKind.DROP, 'peer'))
        controller.back()
        self.assertEqual(controller.state.route, Route('V16'))
        self.assertFalse(controller.notifications.store.selecting)
        self.assertFalse(controller.notifications.store.selected)
        controller.back()
        self.assertEqual(controller.state.route, Route('V06'))

    def test_navigation_has_no_communication_side_effect(self) -> None:
        """Peer LIVE, selectors and secondary routes never initiate calls."""
        controller = GuiController(
            FrontendLaunchContext(
                'test',
                Mock(
                    profile_state=lambda: FrontendProfileState(
                        'test', True, False, False
                    )
                ),
            )
        )
        client = Mock()
        controller.client = client
        controller.state.covered = False
        for route in (
            Route('V09', 'alice', Delivery.LIVE),
            Route('V17'),
            Route('V16'),
            Route('V12'),
        ):
            controller.navigate(route)
            controller.state.back()
        self.assertEqual(client.mock_calls, [])

    def test_drafts_separate_projections_and_refuse_overflow(self) -> None:
        """Draft admission does not overwrite other contexts or persist data."""
        state = GuiState()
        self.assertTrue(state.set_draft('alice', Delivery.DROP, 'drop'))
        self.assertTrue(state.set_draft('alice', Delivery.LIVE, 'live'))
        self.assertFalse(
            state.set_draft('bob', Delivery.DROP, 'x' * GuiLimits.TEXT_BYTES)
        )
        self.assertEqual(state.drafts[('alice', Delivery.DROP)], 'drop')
        state.abandon()
        self.assertEqual(state.drafts, {})
        self.assertTrue(state.covered)

    def test_mailbox_does_not_revision_filter_content(self) -> None:
        """A low-revision media result is still delivered to the consumer."""
        mailbox = Mailbox()
        event = VoiceDataEvent(
            alias='alice',
            onion='alice',
            msg_id='turn',
            offset=0,
            data='YQ==',
            direction=MessageDirectionCode.IN,
            delivery=Delivery.LIVE,
            codec='test',
            next_offset=1,
            size_bytes=1,
            complete=True,
            revision=1,
        )
        self.assertTrue(mailbox.put(Update(1, 'media', event)))
        self.assertIs(mailbox.take().event, event)

    def test_mailbox_count_and_bytes_fail_explicitly(self) -> None:
        """Overflow retains a separate signal and does not claim complete delivery."""
        mailbox = Mailbox()
        for _ in range(GuiLimits.QUEUE_RECORDS):
            self.assertTrue(mailbox.put(Update(1, 'event')))
        self.assertFalse(mailbox.put(Update(1, 'event')))
        self.assertTrue(mailbox.overloaded)
        mailbox.clear()
        self.assertFalse(
            mailbox.put(Update(1, 'event', status='x' * (GuiLimits.QUEUE_BYTES + 1)))
        )

    def test_stale_activation_cannot_install_snapshot(self) -> None:
        """Abandoned profile callbacks cannot uncover a new profile."""
        controller = GuiController(
            FrontendLaunchContext(
                'test',
                Mock(
                    profile_state=lambda: FrontendProfileState(
                        'test', True, False, False
                    )
                ),
            )
        )
        old = controller.state.generation
        controller.close()
        controller.mailbox.put(
            Update(old, 'bootstrap', RuntimeSnapshotEvent('old', 'old'))
        )
        controller.poll()
        self.assertIsNone(controller.state.snapshot)
        self.assertTrue(controller.state.covered)

    def test_simulator_never_bootstraps_host_or_production_client(self) -> None:
        """Simulation has no injected destructive or host-power path."""
        host = Mock()
        controller = GuiController(FrontendLaunchContext('test', host), simulator=True)
        with patch('metor.ui.gui.runtime.activation.MetorClient') as client:
            controller.open_profile()
            controller.close()
            client.assert_not_called()
        self.assertEqual(host.mock_calls, [])

    def test_double_submit_and_unknown_send_keep_one_identity(self) -> None:
        """One pending turn survives a lost result without a second send."""
        controller = GuiController(
            FrontendLaunchContext(
                'test',
                Mock(
                    profile_state=lambda: FrontendProfileState(
                        'test', True, False, False
                    )
                ),
            )
        )
        controller.state.covered = False
        controller.state.set_draft('alice', Delivery.DROP, 'hello')
        arrived, finish = threading.Event(), threading.Event()
        client = Mock()

        def request(*_args: object) -> None:
            arrived.set()
            finish.wait(2)
            return None

        client.request.side_effect = request
        controller.client = client
        controller.send_text('alice', Delivery.DROP)
        self.assertTrue(arrived.wait(2))
        controller.send_text('alice', Delivery.DROP)
        finish.set()
        controller._worker.join(2)
        controller.poll()
        controller.send_text('alice', Delivery.DROP)
        self.assertEqual(client.request.call_count, 1)
        self.assertEqual(controller.state.drafts[('alice', Delivery.DROP)], 'hello')

    def test_confirmed_send_clears_only_matching_draft(self) -> None:
        """New typing is preserved when an older submission is accepted."""
        controller = GuiController(
            FrontendLaunchContext(
                'test',
                Mock(
                    profile_state=lambda: FrontendProfileState(
                        'test', True, False, False
                    )
                ),
            )
        )
        controller.text.operations['A11:one'] = ('alice', Delivery.DROP, 'old')
        controller.state.set_draft('alice', Delivery.DROP, 'new')
        controller.mailbox.put(Update(0, 'A11:one', DropQueuedEvent('Alice', 'alice')))
        controller.poll()
        self.assertEqual(controller.state.drafts[('alice', Delivery.DROP)], 'new')

    def test_wrong_identity_or_absent_receipt_never_clears_unknown_text(self) -> None:
        """A correlated response still needs the captured message identity."""
        controller = GuiController(
            FrontendLaunchContext(
                'test',
                Mock(
                    profile_state=lambda: FrontendProfileState(
                        'test', True, False, False
                    )
                ),
            )
        )
        controller.text.operations['A11:one'] = ('alice', Delivery.LIVE, 'keep')
        controller.state.set_draft('alice', Delivery.LIVE, 'keep')
        controller.mailbox.put(Update(0, 'A11:one', TextAcceptedEvent('bob', 'one')))
        controller.poll()
        self.assertEqual(controller.state.drafts[('alice', Delivery.LIVE)], 'keep')
        controller.mailbox.put(
            Update(0, 'text-check:A11:one', MessageOutcomeEvent('alice', 'one'))
        )
        controller.poll()
        self.assertIn('A11:one', controller._unknown_actions)
        controller.mailbox.put(
            Update(
                0,
                'text-check:A11:one',
                MessageOutcomeEvent(
                    'alice',
                    'one',
                    delivery=Delivery.LIVE,
                    status=MessageStatusCode.DELIVERED,
                ),
            )
        )
        controller.poll()
        self.assertNotIn(('alice', Delivery.LIVE), controller.state.drafts)
        self.assertNotIn('A11:one', controller._unknown_actions)

    def test_cancelled_prompt_clears_and_unblocks_worker(self) -> None:
        """Cancellation cannot strand a worker or retain a response for reuse."""
        bridge = Interactions(0, Mailbox())
        result: list[str | None] = []
        thread = threading.Thread(
            target=lambda: result.append(bridge.get_unlock_password())
        )
        thread.start()
        bridge.cancel()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [None])
        self.assertIsNone(bridge.prompt)

    def test_startup_credential_is_consumed_once_and_cancellation_clears_it(
        self,
    ) -> None:
        """Graphical bootstrap reuses the host's credential only for its first proof."""
        bridge = Interactions(0, Mailbox())
        provider = OneUseSecretProvider('test-password')
        bridge.startup_secret(provider)
        challenge, salt = '11' * 32, '22' * 16
        self.assertEqual(
            bridge.get_session_auth_proof(challenge, salt),
            build_session_auth_proof('test-password', challenge, salt),
        )
        self.assertIsNone(provider.take())
        replacement = OneUseSecretProvider('unused')
        bridge.startup_secret(replacement)
        bridge.cancel()
        self.assertIsNone(replacement.take())
        self.assertIsNone(bridge.get_unlock_password())

    def test_failed_bootstrap_disconnects_and_remains_covered(self) -> None:
        """A failed SDK snapshot cannot leak its authenticated connection."""
        host, client = Mock(), Mock()
        host.profile_state.return_value = FrontendProfileState(
            'test', True, False, True
        )
        secret = OneUseSecretProvider('unused')
        host.bootstrap.return_value.session_auth = secret
        host.bootstrap.return_value.port = 1234
        client.runtime_snapshot.side_effect = OSError('test connection loss')
        controller = GuiController(FrontendLaunchContext('test', host))
        with patch('metor.ui.gui.runtime.activation.MetorClient', return_value=client):
            self.assertTrue(controller.open_profile())
            controller._worker.join(2)
        self.assertFalse(controller._worker.is_alive())
        controller.poll()
        client.disconnect.assert_called_once()
        self.assertIsNone(secret.take())
        self.assertIsNone(controller.client)
        self.assertTrue(controller.state.covered)


class BackgroundAdmissionTests(unittest.TestCase):
    """One foreground action can wait behind a read-only refresh without becoming duplicate work."""

    def test_explicit_action_waits_behind_background_refresh_once(self) -> None:
        """The native Unlock action remains admissible while background IPC is in flight.

        Args:
            None
        Returns:
            None
        """
        controller = GuiController(
            FrontendLaunchContext(
                'fixture',
                Mock(
                    profile_state=lambda: FrontendProfileState(
                        'fixture', True, False, False
                    )
                ),
            ),
            simulator=True,
        )
        release = threading.Event()
        self.addCleanup(release.set)
        self.addCleanup(controller.close)
        ran: list[str] = []

        def refresh():
            release.wait(5)
            return None

        def action():
            ran.append('action')
            return None

        self.assertTrue(controller.submit('security:state', refresh, background=True))
        self.assertTrue(controller.submit('security:unlock', action))
        self.assertFalse(controller.submit('security:unlock', action))
        self.assertTrue(controller.state.busy)
        self.assertFalse(ran)
        release.set()
        controller._worker.join(5)
        controller.poll()
        controller._worker.join(5)
        self.assertEqual(ran, ['action'])

    def test_completed_background_read_cannot_clear_a_new_foreground_action(
        self,
    ) -> None:
        """An older read result retains the busy state of a newer in-flight write.

        Args:
            None
        Returns:
            None
        """
        controller = GuiController(
            FrontendLaunchContext(
                'fixture',
                Mock(
                    profile_state=lambda: FrontendProfileState(
                        'fixture', True, False, False
                    )
                ),
            ),
            simulator=True,
        )
        self.addCleanup(controller.close)
        release = threading.Event()
        started = threading.Event()
        self.addCleanup(release.set)

        def write() -> None:
            """Holds the later foreground operation while the prior result is installed.

            Args:
                None
            Returns:
                None
            """
            started.set()
            if not release.wait(5):
                raise TimeoutError('Test foreground operation was not released')

        self.assertTrue(
            controller.submit('background:read', lambda: None, background=True)
        )
        assert controller._worker is not None
        controller._worker.join(5)
        self.assertFalse(controller._worker.is_alive())
        self.assertTrue(controller.submit('foreground:write', write))
        self.assertTrue(started.wait(5))
        self.assertTrue(controller.state.busy)
        controller.poll()
        self.assertTrue(controller.state.busy)
        release.set()
        controller._worker.join(5)
        controller.poll()
        self.assertFalse(controller.state.busy)


if __name__ == '__main__':
    unittest.main()
