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
    AcceptCommand,
    create_event,
    AutoFallbackQueuedEvent,
    AutoReconnectScheduledEvent,
    ConnectionActor,
    ConnectionConnectingEvent,
    ConnectionOrigin,
    ConnectionFailedEvent,
    ConnectionReasonCode,
    ConnectedEvent,
    ConnectionsStateEvent,
    DisconnectedEvent,
    EventType,
    InitEvent,
    RenameSuccessEvent,
    RejectCommand,
    RetunnelFailedEvent,
    RetunnelInitiatedEvent,
    RetunnelSuccessEvent,
    RuntimeErrorCode,
    SendDropCommand,
    SwitchCommand,
    MsgCommand,
)
from metor.ui import Theme
from metor.ui.chat.command import CommandDispatcher
from metor.ui.chat.engine import Chat
from metor.ui.chat.event.handler import EventHandler
from metor.ui.chat.models import ChatMessageType, ChatTransportState


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

    def get_int(self, _key: object) -> int:
        """
        Returns int for the test scenario.

        Args:
            _key (object): The key.

        Returns:
            int: The computed return value.
        """

        return 3


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

    def test_disconnect_during_bootstrap_after_auth_adds_blank_line(self) -> None:
        """
        Verifies that prechat bootstrap errors are separated from auth prompts.

        Args:
            None

        Returns:
            None
        """

        renderer = Mock()
        chat = self._build_chat(renderer)
        chat._ipc = Mock()
        chat._ipc.read_event.side_effect = [
            create_event(
                EventType.AUTH_REQUIRED,
                {
                    'challenge': 'challenge',
                    'salt': 'salt',
                },
            ),
            None,
        ]

        with (
            patch(
                'metor.ui.chat.engine.get_session_auth_prompt',
                return_value='Enter Master Password: ',
            ),
            patch(
                'metor.ui.chat.engine.prompt_session_auth_proof', return_value='proof'
            ),
            patch('builtins.print') as print_mock,
        ):
            result = chat._bootstrap_ipc_session()

        self.assertFalse(result)
        print_mock.assert_called_once_with(
            f'\n{Theme.RED}Connection to Daemon lost! Exiting...{Theme.RESET}',
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

    def test_send_chat_message_buffers_while_retunneling(self) -> None:
        """
        Verifies that send chat message defers via the daemon while retunneling.

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
        self.assertIsInstance(sent_cmd, MsgCommand)
        self.assertEqual(
            sent_cmd.msg_id, renderer.print_message.call_args.kwargs['msg_id']
        )
        self.assertFalse(
            chat._session.has_buffered_outgoing_messages(
                'alice',
                'aliceonion1234567890',
            )
        )
        renderer.print_message.assert_called_once()
        self.assertFalse(renderer.print_message.call_args.kwargs['is_drop'])
        self.assertTrue(renderer.print_message.call_args.kwargs['is_pending'])

    def test_send_chat_message_uses_daemon_buffer_during_grace_reconnect(self) -> None:
        """
        Verifies that send chat message defers via the daemon during grace reconnect.

        Args:
            None

        Returns:
            None
        """

        renderer = Mock()
        chat = self._build_chat(renderer)
        chat._ipc = Mock()
        chat._session.focused_alias = 'alice'
        chat._session.remember_peer('alice', 'aliceonion1234567890')

        handler = EventHandler(
            ipc=chat._ipc,
            session=chat._session,
            renderer=renderer,
            init_event=Mock(),
            conn_event=Mock(),
            get_notification_buffer_seconds=lambda: 0.0,
            has_auto_reconnect=lambda: True,
        )
        handler.handle(
            ConnectionConnectingEvent(
                alias='alice',
                onion='aliceonion1234567890',
                origin=ConnectionOrigin.GRACE_RECONNECT,
                actor=ConnectionActor.SYSTEM,
            )
        )
        renderer.print_message.reset_mock()

        chat._send_chat_message('hello during reconnect grace')

        sent_cmd = chat._ipc.send_command.call_args.args[0]
        self.assertIsInstance(sent_cmd, MsgCommand)
        self.assertEqual(
            sent_cmd.msg_id, renderer.print_message.call_args.kwargs['msg_id']
        )
        self.assertFalse(
            chat._session.has_buffered_outgoing_messages(
                'alice',
                'aliceonion1234567890',
            )
        )
        renderer.print_message.assert_called_once()
        self.assertFalse(renderer.print_message.call_args.kwargs['is_drop'])
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
            has_auto_reconnect=lambda: True,
        )

        handler.handle(
            RetunnelInitiatedEvent(alias='alice', onion='aliceonion1234567890')
        )
        self.assertTrue(session.is_retunneling('alice'))
        self.assertFalse(session.is_live_transport_available('alice'))
        renderer.set_focus.assert_called_once_with(
            'alice',
            ChatTransportState.SWITCHING,
        )

        handler.handle(
            RetunnelSuccessEvent(alias='alice', onion='aliceonion1234567890')
        )
        self.assertFalse(session.is_retunneling('alice'))
        self.assertTrue(session.is_live_transport_available('alice'))
        self.assertEqual(renderer.set_focus.call_args.args[1], ChatTransportState.LIVE)

    def test_retunnel_success_flushes_buffered_messages_live(self) -> None:
        """
        Verifies that buffered retunnel messages flush as live after recovery.

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
        session.mark_retunneling('alice', 'aliceonion1234567890')
        session.buffer_outgoing_message(
            alias='alice',
            text='hello during retunnel',
            msg_id='msg-1',
            onion='aliceonion1234567890',
        )
        handler = EventHandler(
            ipc=ipc,
            session=session,
            renderer=renderer,
            init_event=Mock(),
            conn_event=Mock(),
            get_notification_buffer_seconds=lambda: 0.0,
            has_auto_reconnect=lambda: True,
        )

        handler.handle(
            RetunnelSuccessEvent(alias='alice', onion='aliceonion1234567890')
        )

        sent_cmd = ipc.send_command.call_args.args[0]
        self.assertEqual(sent_cmd.msg_id, 'msg-1')
        self.assertFalse(
            session.has_buffered_outgoing_messages('alice', 'aliceonion1234567890')
        )

    def test_auto_reconnect_failure_flushes_buffered_messages_to_drop(self) -> None:
        """
        Verifies that buffered reconnect messages fall back to drops on terminal failure.

        Args:
            None

        Returns:
            None
        """

        renderer = Mock()
        ipc = Mock()
        session = self._build_chat(renderer)._session
        session.focused_alias = 'alice'
        session.remember_peer('alice', 'aliceonion1234567890')
        session.set_transport_state(
            ChatTransportState.RECONNECTING,
            'alice',
            'aliceonion1234567890',
        )
        session.buffer_outgoing_message(
            alias='alice',
            text='hello during reconnect',
            msg_id='msg-1',
            onion='aliceonion1234567890',
        )
        handler = EventHandler(
            ipc=ipc,
            session=session,
            renderer=renderer,
            init_event=Mock(),
            conn_event=Mock(),
            get_notification_buffer_seconds=lambda: 0.0,
            has_auto_reconnect=lambda: True,
        )

        handler.handle(
            ConnectionFailedEvent(
                alias='alice',
                onion='aliceonion1234567890',
                actor=ConnectionActor.SYSTEM,
                origin=ConnectionOrigin.AUTO_RECONNECT,
                reason_code=None,
                error=None,
            )
        )

        sent_cmd = ipc.send_command.call_args.args[0]
        self.assertIsInstance(sent_cmd, SendDropCommand)
        renderer.apply_fallback_to_drop.assert_called_once_with(['msg-1'])
        self.assertEqual(session.get_transport_state('alice'), ChatTransportState.DROP)

    def test_auto_reconnect_schedule_updates_prompt_state(self) -> None:
        """
        Verifies that automatic reconnect uses the reconnecting prompt state.

        Args:
            None

        Returns:
            None
        """

        renderer = Mock()
        session = self._build_chat(renderer)._session
        session.focused_alias = 'alice'
        session.remember_peer('alice', 'aliceonion1234567890')
        handler = EventHandler(
            ipc=Mock(),
            session=session,
            renderer=renderer,
            init_event=Mock(),
            conn_event=Mock(),
            get_notification_buffer_seconds=lambda: 0.0,
            has_auto_reconnect=lambda: True,
        )

        handler.handle(
            AutoReconnectScheduledEvent(
                alias='alice',
                onion='aliceonion1234567890',
                actor=ConnectionActor.SYSTEM,
                origin=ConnectionOrigin.AUTO_RECONNECT,
            )
        )

        renderer.set_focus.assert_called_once_with(
            'alice',
            ChatTransportState.RECONNECTING,
        )

    def test_grace_reconnect_updates_prompt_and_uses_reconnected_copy(self) -> None:
        """
        Verifies that grace reconnect uses peer-side reconnecting/live UX.

        Args:
            None

        Returns:
            None
        """

        renderer = Mock()
        session = self._build_chat(renderer)._session
        session.focused_alias = 'alice'
        session.remember_peer('alice', 'aliceonion1234567890')
        handler = EventHandler(
            ipc=Mock(),
            session=session,
            renderer=renderer,
            init_event=Mock(),
            conn_event=Mock(),
            get_notification_buffer_seconds=lambda: 0.0,
            has_auto_reconnect=lambda: True,
        )

        handler.handle(
            ConnectionConnectingEvent(
                alias='alice',
                onion='aliceonion1234567890',
                origin=ConnectionOrigin.GRACE_RECONNECT,
                actor=ConnectionActor.SYSTEM,
            )
        )

        renderer.set_focus.assert_called_once_with(
            'alice',
            ChatTransportState.RECONNECTING,
        )
        renderer.print_message.reset_mock()
        renderer.set_focus.reset_mock()

        handler.handle(
            ConnectedEvent(
                alias='alice',
                onion='aliceonion1234567890',
                origin=ConnectionOrigin.GRACE_RECONNECT,
                actor=ConnectionActor.SYSTEM,
            )
        )

        self.assertTrue(session.is_live_transport_available('alice'))
        renderer.set_focus.assert_called_once_with('alice', ChatTransportState.LIVE)
        self.assertIn('Reconnected to', renderer.print_message.call_args.args[0])

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
            has_auto_reconnect=lambda: True,
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
            has_auto_reconnect=lambda: True,
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
        renderer.set_focus.assert_called_once_with(None, ChatTransportState.DROP)
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
            has_auto_reconnect=lambda: True,
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
            has_auto_reconnect=lambda: True,
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
        renderer.set_focus.assert_called_once_with(
            'alice',
            ChatTransportState.DROP,
        )
        ipc.send_command.assert_not_called()

    def test_remote_disconnect_after_retunnel_stays_drop_and_sends_drop_immediately(
        self,
    ) -> None:
        """
        Verifies that terminal peer disconnect after a retunneled session stays in drop mode.

        Args:
            None

        Returns:
            None
        """

        renderer = Mock()
        ipc = Mock()
        chat = self._build_chat(renderer)
        chat._ipc = ipc
        chat._session.focused_alias = 'alice'
        chat._session.active_connections = ['alice']
        chat._session.remember_peer('alice', 'aliceonion1234567890')
        handler = EventHandler(
            ipc=ipc,
            session=chat._session,
            renderer=renderer,
            init_event=Mock(),
            conn_event=Mock(),
            get_notification_buffer_seconds=lambda: 0.0,
            has_auto_reconnect=lambda: True,
        )

        handler.handle(
            DisconnectedEvent(
                alias='alice',
                onion='aliceonion1234567890',
                actor=ConnectionActor.REMOTE,
                origin=ConnectionOrigin.RETUNNEL,
            )
        )

        self.assertEqual(
            chat._session.get_transport_state('alice'),
            ChatTransportState.DROP,
        )
        renderer.set_focus.assert_called_once_with(
            'alice',
            ChatTransportState.DROP,
        )
        ipc.send_command.assert_not_called()

        renderer.print_message.reset_mock()
        ipc.send_command.reset_mock()

        chat._send_chat_message('hello after peer disconnect')

        sent_cmd = ipc.send_command.call_args.args[0]
        self.assertIsInstance(sent_cmd, SendDropCommand)
        self.assertTrue(renderer.print_message.call_args.kwargs['is_drop'])
        self.assertTrue(renderer.print_message.call_args.kwargs['is_pending'])

    def test_terminal_retunnel_reject_stays_drop_even_with_auto_reconnect(
        self,
    ) -> None:
        """
        Verifies that an explicit peer reject of a retunnel reconnect stays terminal in chat.

        Args:
            None

        Returns:
            None
        """

        renderer = Mock()
        ipc = Mock()
        chat = self._build_chat(renderer)
        chat._ipc = ipc
        chat._session.focused_alias = 'alice'
        chat._session.active_connections = ['alice']
        chat._session.remember_peer('alice', 'aliceonion1234567890')
        chat._session.mark_retunneling('alice', 'aliceonion1234567890')
        chat._session.buffer_outgoing_message(
            alias='alice',
            text='hello after rejected retunnel',
            msg_id='msg-1',
            onion='aliceonion1234567890',
        )
        handler = EventHandler(
            ipc=ipc,
            session=chat._session,
            renderer=renderer,
            init_event=Mock(),
            conn_event=Mock(),
            get_notification_buffer_seconds=lambda: 0.0,
            has_auto_reconnect=lambda: True,
        )

        handler.handle(
            DisconnectedEvent(
                alias='alice',
                onion='aliceonion1234567890',
                actor=ConnectionActor.REMOTE,
                origin=ConnectionOrigin.RETUNNEL,
                reason_code=ConnectionReasonCode.PEER_ENDED_SESSION,
            )
        )
        handler.handle(
            RetunnelFailedEvent(
                alias='alice',
                onion='aliceonion1234567890',
                error=None,
                error_code=RuntimeErrorCode.PEER_ENDED_SESSION,
                error_detail='Peer ended the session',
            )
        )

        status_messages = [
            str(call.args[0]) for call in renderer.print_message.call_args_list
        ]
        self.assertTrue(
            any('ended the session' in message for message in status_messages)
        )
        self.assertTrue(
            any(
                'Retunnel failed: Peer ended the session.' in message
                for message in status_messages
            )
        )

        self.assertEqual(
            chat._session.get_transport_state('alice'),
            ChatTransportState.DROP,
        )
        sent_cmd = ipc.send_command.call_args.args[0]
        self.assertIsInstance(sent_cmd, SendDropCommand)
        renderer.apply_fallback_to_drop.assert_called_once_with(['msg-1'])

    def test_rename_during_reconnect_preserves_focus_and_updates_alias_lists(
        self,
    ) -> None:
        """
        Verifies that renaming a reconnecting peer keeps focus stable and updates alias-backed lists.

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
        session.pending_connections = ['alice']
        session.header_active = ['alice', 'bob']
        session.header_pending = ['alice']
        session.header_contacts = ['alice', 'bob']
        session.remember_peer('alice', 'aliceonion1234567890')
        session.set_transport_state(
            ChatTransportState.RECONNECTING,
            'alice',
            'aliceonion1234567890',
        )
        handler = EventHandler(
            ipc=ipc,
            session=session,
            renderer=renderer,
            init_event=Mock(),
            conn_event=Mock(),
            get_notification_buffer_seconds=lambda: 0.0,
            has_auto_reconnect=lambda: True,
        )

        handler.handle(
            RenameSuccessEvent(
                old_alias='alice',
                new_alias='eve',
                onion='aliceonion1234567890',
            )
        )

        self.assertEqual(session.focused_alias, 'eve')
        self.assertEqual(session.active_connections, ['eve', 'bob'])
        self.assertEqual(session.pending_connections, ['eve'])
        self.assertEqual(session.header_active, ['eve', 'bob'])
        self.assertEqual(session.header_pending, ['eve'])
        self.assertEqual(session.header_contacts, ['eve', 'bob'])
        self.assertEqual(
            session.get_transport_state('eve'),
            ChatTransportState.RECONNECTING,
        )
        renderer.set_focus.assert_called_once_with(
            'eve', ChatTransportState.RECONNECTING
        )
        renderer.refresh_alias_bindings.assert_not_called()
        ipc.send_command.assert_not_called()

    def test_accept_without_target_uses_implicit_pending_focus(self) -> None:
        """
        Verifies that accept resolves the focused pending session implicitly.

        Args:
            None

        Returns:
            None
        """

        ipc = Mock()
        renderer = Mock()
        session = self._build_chat(renderer)._session
        session.focused_alias = 'alice'
        session.pending_connections = ['alice', 'bob']
        dispatcher = CommandDispatcher(ipc=ipc, session=session, renderer=renderer)

        handled = dispatcher.dispatch('/accept')

        self.assertTrue(handled)
        sent_cmd = ipc.send_command.call_args.args[0]
        self.assertIsInstance(sent_cmd, AcceptCommand)
        self.assertEqual(sent_cmd.target, 'alice')
        self.assertIsNone(session.pending_accept_focus_target)
        renderer.print_message.assert_not_called()

    def test_reject_without_target_uses_implicit_pending_focus(self) -> None:
        """
        Verifies that reject resolves the focused pending session implicitly.

        Args:
            None

        Returns:
            None
        """

        ipc = Mock()
        renderer = Mock()
        session = self._build_chat(renderer)._session
        session.focused_alias = 'alice'
        session.pending_connections = ['alice', 'bob']
        dispatcher = CommandDispatcher(ipc=ipc, session=session, renderer=renderer)

        handled = dispatcher.dispatch('/reject')

        self.assertTrue(handled)
        sent_cmd = ipc.send_command.call_args.args[0]
        self.assertIsInstance(sent_cmd, RejectCommand)
        self.assertEqual(sent_cmd.target, 'alice')
        renderer.print_message.assert_not_called()


if __name__ == '__main__':
    unittest.main()
