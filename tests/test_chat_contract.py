"""Regression tests for chat disconnect exit behavior."""

# ruff: noqa: E402

import sys
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.data.profile import ProfileManager
from metor.core.api import (
    AutoFallbackQueuedEvent,
    ConnectionActor,
    ConnectionOrigin,
    ConnectionsStateEvent,
    DisconnectedEvent,
    InitEvent,
    RetunnelInitiatedEvent,
    RetunnelSuccessEvent,
    SendDropCommand,
    SwitchCommand,
)
from metor.ui import Theme
from metor.ui.chat.engine import Chat
from metor.ui.chat.event.handler import EventHandler
from metor.ui.chat.models import ChatMessageType


class _DummyConfig:
    """
    Provides a dummy config test double.
    """

    def get_float(self, _key: object) -> float:
        """
        Returns float for the test scenario.

        Args:
            _key (object): The key.

        Returns:
            float: The computed return value.
        """

        return 0.1


class _DummyProfileManager:
    """
    Provides a dummy profile manager test double.
    """

    def __init__(self) -> None:
        """
        Initializes the dummy profile manager helper.

        Args:
            None

        Returns:
            None
        """

        self.config: _DummyConfig = _DummyConfig()

    def get_daemon_port(self) -> int:
        """
        Returns daemon port for the test scenario.

        Args:
            None

        Returns:
            int: The computed return value.
        """

        return 43111


class ChatContractTests(unittest.TestCase):
    """
    Covers chat contract regression scenarios.
    """

    @staticmethod
    def _build_chat(renderer: Mock) -> Chat:
        """
        Builds chat for the surrounding tests.

        Args:
            renderer (Mock): The renderer.

        Returns:
            Chat: The computed return value.
        """

        with (
            patch('metor.ui.chat.engine.Renderer', return_value=renderer),
            patch('metor.ui.chat.engine.IpcClient'),
            patch('metor.ui.chat.engine.EventHandler'),
            patch('metor.ui.chat.engine.CommandDispatcher'),
        ):
            return Chat(cast(ProfileManager, _DummyProfileManager()))

    def test_disconnect_exit_message_skips_prompt_during_chat_loop(self) -> None:
        """
        Verifies that disconnect exit message skips prompt during chat loop.

        Args:
            None

        Returns:
            None
        """

        renderer = Mock()
        ipc_client = Mock()
        ipc_client.connect.return_value = True
        chat = self._build_chat(renderer)

        def trigger_disconnect(_stop_event: object) -> None:
            """
            Executes trigger disconnect for the test scenario.

            Args:
                _stop_event (object): The stop event.

            Returns:
                None
            """

            chat._disconnect_event.set()
            return None

        renderer.read_line.side_effect = trigger_disconnect

        with (
            patch('metor.ui.chat.engine.IpcClient', return_value=ipc_client),
            patch('metor.ui.chat.engine.EventHandler'),
            patch('metor.ui.chat.engine.CommandDispatcher'),
            patch.object(Chat, '_bootstrap_ipc_session', return_value=True),
            patch.object(Chat, '_print_header'),
            patch.object(Chat, '_shutdown'),
        ):
            chat.run()

        renderer.clear_input_area.assert_called()
        renderer.print_divider.assert_called_once_with(skip_prompt=True)
        renderer.print_message.assert_any_call(
            f'{Theme.RED}Connection to Daemon lost! Exiting...{Theme.RESET}',
            msg_type=ChatMessageType.RAW,
            skip_prompt=True,
        )

    def test_disconnect_during_bootstrap_uses_prechat_console_output(self) -> None:
        """
        Verifies that disconnect during bootstrap uses prechat console output.

        Args:
            None

        Returns:
            None
        """

        renderer = Mock()
        chat = self._build_chat(renderer)
        chat._ipc = Mock()
        chat._ipc.read_event.return_value = None

        with patch('builtins.print') as print_mock:
            result = chat._bootstrap_ipc_session()

        self.assertFalse(result)
        renderer.clear_input_area.assert_not_called()
        renderer.print_divider.assert_not_called()
        renderer.print_message.assert_not_called()
        print_mock.assert_called_once_with(
            f'{Theme.RED}Connection to Daemon lost! Exiting...{Theme.RESET}',
            flush=True,
        )

    def test_bootstrap_populates_session_state_before_header(self) -> None:
        """
        Verifies that bootstrap populates session state before header.

        Args:
            None

        Returns:
            None
        """

        renderer = Mock()
        chat = self._build_chat(renderer)
        chat._ipc = Mock()
        chat._ipc.read_event.side_effect = [
            InitEvent(onion='abc123'),
            ConnectionsStateEvent(
                active=['alice'],
                pending=['bob'],
                contacts=['alice', 'bob', 'carol'],
                is_header=True,
            ),
        ]

        result = chat._bootstrap_ipc_session()

        self.assertTrue(result)
        self.assertEqual(chat._session.my_onion, 'abc123')
        self.assertEqual(chat._session.header_active, ['alice'])
        self.assertEqual(chat._session.header_pending, ['bob'])
        self.assertEqual(chat._session.header_contacts, ['alice', 'bob', 'carol'])
        renderer.print_message.assert_not_called()

    def test_send_chat_message_uses_drop_while_retunneling(self) -> None:
        """
        Verifies that send chat message uses drop while retunneling.

        Args:
            None

        Returns:
            None
        """

        renderer = Mock()
        chat = self._build_chat(renderer)
        chat._ipc = Mock()
        chat._session.focused_alias = 'alice'
        chat._session.active_connections = ['alice']
        chat._session.remember_peer('alice', 'aliceonion1234567890')
        chat._session.mark_retunneling('alice', 'aliceonion1234567890')

        chat._send_chat_message('hello during retunnel')

        sent_cmd = chat._ipc.send_command.call_args.args[0]
        self.assertIsInstance(sent_cmd, SendDropCommand)
        self.assertEqual(sent_cmd.target, 'alice')
        renderer.print_message.assert_called_once()
        self.assertTrue(renderer.print_message.call_args.kwargs['is_drop'])
        self.assertTrue(renderer.print_message.call_args.kwargs['is_pending'])

    def test_retunnel_events_toggle_live_send_state(self) -> None:
        """
        Verifies that retunnel events toggle live send state.

        Args:
            None

        Returns:
            None
        """

        renderer = Mock()
        session = self._build_chat(renderer)._session
        session.focused_alias = 'alice'
        session.active_connections = ['alice']
        handler = EventHandler(
            ipc=Mock(),
            session=session,
            renderer=renderer,
            init_event=Mock(),
            conn_event=Mock(),
            get_notification_buffer_seconds=lambda: 0.0,
        )

        handler.handle(
            RetunnelInitiatedEvent(alias='alice', onion='aliceonion1234567890')
        )
        self.assertTrue(session.is_retunneling('alice'))
        self.assertFalse(session.is_live_transport_available('alice'))

        handler.handle(
            RetunnelSuccessEvent(alias='alice', onion='aliceonion1234567890')
        )
        self.assertFalse(session.is_retunneling('alice'))
        self.assertTrue(session.is_live_transport_available('alice'))

    def test_auto_fallback_queued_event_converts_pending_live_message_to_drop(
        self,
    ) -> None:
        """
        Verifies that auto fallback queued event converts pending live message to drop.

        Args:
            None

        Returns:
            None
        """

        renderer = Mock()
        session = self._build_chat(renderer)._session
        handler = EventHandler(
            ipc=Mock(),
            session=session,
            renderer=renderer,
            init_event=Mock(),
            conn_event=Mock(),
            get_notification_buffer_seconds=lambda: 0.0,
        )

        handler.handle(
            AutoFallbackQueuedEvent(
                alias='alice',
                onion='aliceonion1234567890',
                msg_id='msg-1',
            )
        )

        renderer.apply_fallback_to_drop.assert_called_once_with(['msg-1'])

        renderer.apply_fallback_to_drop.assert_called_once_with(['msg-1'])

    def test_local_disconnect_of_focused_session_clears_focus(self) -> None:
        """
        Verifies that local disconnect of focused session clears focus.

        Args:
            None

        Returns:
            None
        """

        renderer = Mock()
        ipc = Mock()
        session = self._build_chat(renderer)._session
        session.focused_alias = 'alice'
        session.active_connections = ['alice']
        session.remember_peer('alice', 'aliceonion1234567890')
        handler = EventHandler(
            ipc=ipc,
            session=session,
            renderer=renderer,
            init_event=Mock(),
            conn_event=Mock(),
            get_notification_buffer_seconds=lambda: 0.0,
        )

        handler.handle(
            DisconnectedEvent(
                alias='alice',
                onion='aliceonion1234567890',
                actor=ConnectionActor.LOCAL,
                origin=ConnectionOrigin.MANUAL,
            )
        )

        self.assertIsNone(session.focused_alias)
        renderer.set_focus.assert_called_once_with(None, False)
        sent_cmd = ipc.send_command.call_args.args[0]
        self.assertIsInstance(sent_cmd, SwitchCommand)
        self.assertIsNone(sent_cmd.target)

    def test_local_disconnect_of_other_session_preserves_focus(self) -> None:
        """
        Verifies that local disconnect of other session preserves focus.

        Args:
            None

        Returns:
            None
        """

        renderer = Mock()
        ipc = Mock()
        session = self._build_chat(renderer)._session
        session.focused_alias = 'alice'
        session.active_connections = ['alice', 'bob']
        session.remember_peer('alice', 'aliceonion1234567890')
        session.remember_peer('bob', 'bobonion12345678901234')
        handler = EventHandler(
            ipc=ipc,
            session=session,
            renderer=renderer,
            init_event=Mock(),
            conn_event=Mock(),
            get_notification_buffer_seconds=lambda: 0.0,
        )

        handler.handle(
            DisconnectedEvent(
                alias='bob',
                onion='bobonion12345678901234',
                actor=ConnectionActor.LOCAL,
                origin=ConnectionOrigin.MANUAL,
            )
        )

        self.assertEqual(session.focused_alias, 'alice')
        renderer.set_focus.assert_not_called()
        ipc.send_command.assert_not_called()

    def test_connection_loss_of_focused_session_preserves_focus(self) -> None:
        """
        Verifies that connection loss of focused session preserves focus.

        Args:
            None

        Returns:
            None
        """

        renderer = Mock()
        ipc = Mock()
        session = self._build_chat(renderer)._session
        session.focused_alias = 'alice'
        session.active_connections = ['alice']
        session.remember_peer('alice', 'aliceonion1234567890')
        handler = EventHandler(
            ipc=ipc,
            session=session,
            renderer=renderer,
            init_event=Mock(),
            conn_event=Mock(),
            get_notification_buffer_seconds=lambda: 0.0,
        )

        handler.handle(
            DisconnectedEvent(
                alias='alice',
                onion='aliceonion1234567890',
                actor=ConnectionActor.SYSTEM,
                origin=ConnectionOrigin.INCOMING,
            )
        )

        self.assertEqual(session.focused_alias, 'alice')
        renderer.set_focus.assert_called_once_with('alice', is_live=False)
        ipc.send_command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
