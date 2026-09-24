"""Real temporary Core and SDK consumer proof for Terminal Voice metadata."""

import base64
import socket
import threading
import unittest
from typing import cast
from unittest.mock import Mock, patch

from metor.core.api import (
    ContentType,
    Delivery,
    InboxCountsEvent,
    IpcEvent,
    ListRetainedMessagesCommand,
    MarkReadCommand,
    MessageDirectionCode,
    RetainedMessagesEvent,
    UnreadMessagesEvent,
)
from metor.data import MessageDirection, MessageStatus
from metor.ui.terminal.chat.command import CommandDispatcher
from metor.ui.terminal.chat.event.handler import EventHandler
from metor.ui.terminal.chat.session import Session

import test_gui_producers as producer_support


class TerminalVoiceCoreTests(unittest.TestCase):
    """Verify metadata display against one real temporary Core and two SDK clients."""

    def test_inventory_does_not_consume_second_clients_voice(self) -> None:
        """Only the second client's explicit read and release changes Voice state.

        Args:
            None
        Returns:
            None
        """
        fixture = producer_support.GuiProducerTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        renderer = Mock()
        handler = EventHandler(
            fixture.client._ipc,
            Session(),
            renderer,
            threading.Event(),
            threading.Event(),
            lambda: 0.0,
            lambda: False,
        )

        class VoiceSocket:
            """Accept only the Core's bounded synthetic commit acknowledgement."""

            def sendall(self, _payload: bytes) -> None:
                """Receive one protocol acknowledgement without a remote peer.

                Args:
                    _payload: Bounded Core acknowledgement.
                Returns:
                    None
                """

        voice = fixture.daemon._network._router._voice
        self.assertIsNotNone(voice)
        assert voice is not None
        conn = cast(socket.socket, VoiceSocket())
        payloads = {'live-voice': b'live bytes', 'drop-voice': b'drop bytes'}
        for msg_id, delivery in (
            ('live-voice', Delivery.LIVE),
            ('drop-voice', Delivery.DROP),
        ):
            payload = payloads[msg_id]
            self.assertFalse(
                voice.receive_begin(
                    conn, fixture.onion, {'id': msg_id, 'codec': 'opus'}, delivery
                )
            )
            self.assertFalse(
                voice.receive_chunk(
                    conn,
                    fixture.onion,
                    {
                        'id': msg_id,
                        'offset': 0,
                        'data': base64.b64encode(payload).decode('ascii'),
                    },
                )
            )
            self.assertFalse(
                voice.receive_end(
                    conn, fixture.onion, {'id': msg_id, 'size': len(payload)}
                )
            )
        text_outcome = fixture.messages.store_inbound_drop_text(
            fixture.onion, 'text-drop', 'temporary text', None, 100
        )
        self.assertEqual(text_outcome.value, 'created')
        live_text = fixture.messages.queue_message(
            fixture.onion,
            MessageDirection.IN,
            Delivery.LIVE,
            ContentType.TEXT,
            '{"text":"temporary live text"}',
            MessageStatus.UNREAD,
            'text-live',
        )
        self.assertFalse(live_text.was_duplicate)
        before = fixture.messages.get_unread_counts()[fixture.onion]
        self.assertEqual(before, 4)
        observed: list[IpcEvent] = []
        failures: list[Exception] = []
        condition = threading.Condition()

        def on_event(event: IpcEvent) -> None:
            """Deliver the real first client's Core events to Terminal.

            Args:
                event: Typed event from the independently connected daemon.
            Returns:
                None
            """
            try:
                handler.handle(event)
            except Exception as exc:
                failures.append(exc)
            finally:
                with condition:
                    observed.append(event)
                    condition.notify_all()

        fixture.client._on_event = on_event
        with patch.object(
            fixture.client._ipc,
            'send_command',
            wraps=fixture.client._ipc.send_command,
        ) as sent:
            handler.handle(InboxCountsEvent(inbox={fixture.onion: before}))
            with condition:
                self.assertTrue(
                    condition.wait_for(
                        lambda: any(
                            isinstance(event, RetainedMessagesEvent)
                            for event in observed
                        ),
                        timeout=5,
                    )
                )
            self.assertFalse(failures)
            self.assertEqual(len(handler._voice._seen), 2)
            self.assertEqual(
                fixture.messages.get_unread_counts()[fixture.onion], before
            )
            dispatcher = CommandDispatcher(
                fixture.client._ipc, handler._session, renderer
            )
            self.assertTrue(dispatcher.dispatch('/inbox ' + fixture.onion))
            with condition:
                self.assertTrue(
                    condition.wait_for(
                        lambda: (
                            any(
                                isinstance(event, UnreadMessagesEvent)
                                for event in observed
                            )
                            and sum(
                                isinstance(event, RetainedMessagesEvent)
                                for event in observed
                            )
                            >= 2
                        ),
                        timeout=5,
                    )
                )
            self.assertFalse(failures)
            sent_commands = [call.args[0] for call in sent.call_args_list]
            pages = [
                command
                for command in sent_commands
                if isinstance(command, ListRetainedMessagesCommand)
            ]
            self.assertEqual(len(pages), 2)
            self.assertTrue(
                any(isinstance(command, MarkReadCommand) for command in sent_commands)
            )
            page_ids = {command.request_id for command in pages}
            self.assertEqual(
                page_ids,
                {
                    event.request_id
                    for event in observed
                    if isinstance(event, RetainedMessagesEvent)
                },
            )
        renderer.print_messages_batch.assert_called_once()
        self.assertEqual(fixture.messages.get_unread_counts()[fixture.onion], 2)
        self.assertEqual(len(handler._voice._seen), 2)
        self.assertEqual(
            {
                entry.msg_id
                for entry in fixture.other.list_retained_messages(
                    direction=MessageDirectionCode.IN
                ).messages
            },
            set(payloads),
        )
        for msg_id, payload in payloads.items():
            data = fixture.other.get_voice_chunk(
                fixture.onion, msg_id, MessageDirectionCode.IN, 0, len(payload)
            )
            self.assertIsNotNone(data)
            assert data is not None
            self.assertEqual(base64.b64decode(data.data), payload)
            self.assertIsNotNone(fixture.other.release_voice(fixture.onion, msg_id))
        self.assertEqual(
            fixture.other.list_retained_messages(
                direction=MessageDirectionCode.IN
            ).messages,
            [],
        )
        self.assertEqual(fixture.messages.get_unread_counts().get(fixture.onion, 0), 0)


if __name__ == '__main__':
    unittest.main()
