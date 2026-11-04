"""Terminal Voice metadata presentation never transfers or consumes media."""

import threading
import unittest
from unittest.mock import Mock, patch

from metor.core.api import (
    ContentType,
    Delivery,
    InboxCountsEvent,
    InboxNotificationEvent,
    InvalidTargetEvent,
    MarkReadCommand,
    ListRetainedMessagesCommand,
    MessageDirectionCode,
    MessageReceivedEvent,
    MessageStatusCode,
    RetainedMessageEntry,
    RetainedMessagesEvent,
    RetainedMessagesUnavailableEvent,
    UnreadMessagesEvent,
    VoiceChunkReceivedEvent,
    VoiceContent,
    VoiceFinalizedEvent,
    VoiceIncomingStartedEvent,
)
from metor.ui.terminal.chat.command import CommandDispatcher
from metor.ui.terminal.chat.event.handler import EventHandler
from metor.ui.terminal.chat.session import Session
from metor.ui.terminal.constants import Constants


class TerminalVoiceTests(unittest.TestCase):
    """Exercises the real terminal event routing with public typed DTOs."""

    def setUp(self) -> None:
        """Builds a metadata-only client and renderer.

        Args:
            None
        Returns:
            None
        """
        self.ipc = Mock()
        self.renderer = Mock()
        self.session = Session()
        self.handler = EventHandler(
            self.ipc,
            self.session,
            self.renderer,
            threading.Event(),
            threading.Event(),
            lambda: 0.0,
            lambda: False,
        )

    def _entry(
        self, msg_id: str, direction: MessageDirectionCode = MessageDirectionCode.IN
    ) -> RetainedMessageEntry:
        """Creates one safe retained Voice descriptor.

        Args:
            msg_id: Logical identity.
            direction: Incoming or outbound direction.
        Returns:
            RetainedMessageEntry: Metadata-only test entry.
        """
        return RetainedMessageEntry(
            onion='peer.onion',
            alias='peer',
            direction=direction,
            delivery=Delivery.DROP,
            status=MessageStatusCode.UNREAD,
            content_type=ContentType.VOICE,
            msg_id=msg_id,
            finalized=True,
        )

    def test_live_events_show_one_hint_without_reading_or_releasing(self) -> None:
        """Ignores stream chunks and deduplicates finalization against push.

        Args:
            None
        Returns:
            None
        """
        self.session.focused_alias = 'peer'
        self.handler.handle(
            VoiceIncomingStartedEvent(
                'peer', 'v1', Delivery.LIVE, 'opus', 0, 'peer.onion'
            )
        )
        for offset in range(Constants.VOICE_NOTICE_IDS + 1):
            self.handler.handle(
                VoiceChunkReceivedEvent('peer', 'v1', offset, 'c2VjcmV0', 'peer.onion')
            )
        self.renderer.print_message.assert_not_called()
        self.handler.handle(
            MessageReceivedEvent(
                alias='peer',
                onion='peer.onion',
                delivery=Delivery.LIVE,
                content=VoiceContent('opaque', 'opus', 6),
                msg_id='v1',
            )
        )
        self.handler.handle(
            VoiceFinalizedEvent(
                msg_id='v1',
                size_bytes=6,
                onion='peer.onion',
                delivery=Delivery.LIVE,
                direction=MessageDirectionCode.IN,
            )
        )
        self.assertEqual(self.renderer.print_message.call_count, 1)
        self.assertIn(
            'Voice message received. Playback is not supported in this frontend.',
            self.renderer.print_message.call_args.args[0],
        )
        self.ipc.send_command.assert_not_called()

    def test_drop_finalization_and_inbox_notification_are_deduplicated(self) -> None:
        """Keeps one hint for an unfocused peer and offers inbox follow-up.

        Args:
            None
        Returns:
            None
        """
        self.handler.handle(
            VoiceFinalizedEvent(
                msg_id='outgoing',
                size_bytes=4,
                onion='peer.onion',
                delivery=Delivery.DROP,
                direction=MessageDirectionCode.OUT,
            )
        )
        self.handler.handle(
            VoiceFinalizedEvent(
                msg_id='drop-1',
                size_bytes=4,
                onion='peer.onion',
                delivery=Delivery.DROP,
                direction=MessageDirectionCode.IN,
            )
        )
        self.handler.handle(
            InboxNotificationEvent(
                alias='peer',
                onion='peer.onion',
                source_id='drop-1',
            )
        )
        self.renderer.print_message.assert_called_once()
        self.assertIn('/inbox', self.renderer.print_message.call_args.args[0])
        self.ipc.send_command.assert_not_called()

    def test_inventory_is_bounded_and_non_consuming(self) -> None:
        """Pages a fixed number of times and never fetches Voice bytes.

        Args:
            None
        Returns:
            None
        """
        self.handler.handle(InboxCountsEvent(inbox={}))
        for index in range(Constants.VOICE_INVENTORY_PAGES):
            command = self.ipc.send_command.call_args.args[0]
            self.assertIsInstance(command, ListRetainedMessagesCommand)
            self.assertEqual(command.direction, MessageDirectionCode.IN)
            self.assertEqual(command.limit, Constants.DEFAULT_RETAINED_PAGE_SIZE)
            self.assertIsNotNone(command.request_id)
            self.handler.handle(
                RetainedMessagesEvent(
                    messages=[
                        self._entry('v1'),
                        self._entry('out', MessageDirectionCode.OUT),
                    ],
                    next_cursor=f'cursor-{index}',
                    request_id=command.request_id,
                )
            )
        self.assertEqual(
            self.ipc.send_command.call_count, Constants.VOICE_INVENTORY_PAGES
        )
        self.assertEqual(len(self.handler._voice._seen), 1)
        self.assertIn('truncated', self.renderer.print_message.call_args.args[0])
        self.handler.handle(RetainedMessagesEvent(messages=[self._entry('ignored')]))
        self.assertEqual(
            self.ipc.send_command.call_count, Constants.VOICE_INVENTORY_PAGES
        )

    def test_inventory_failure_stops_scan_and_dedupe_stays_bounded(self) -> None:
        """Does not retry stale cursors or keep unbounded rendered identities.

        Args:
            None
        Returns:
            None
        """
        self.handler._voice.request_inventory()
        request_id = self.ipc.send_command.call_args.args[0].request_id
        self.handler.handle(
            RetainedMessagesUnavailableEvent(reason='stale', request_id=request_id)
        )
        self.assertIn(
            'metadata is unavailable', self.renderer.print_message.call_args.args[0]
        )
        self.handler.handle(RetainedMessagesEvent(messages=[self._entry('ignored')]))
        self.assertEqual(self.ipc.send_command.call_count, 1)
        for index in range(Constants.VOICE_NOTICE_IDS + 1):
            self.handler._voice.announce(None, 'peer.onion', 'peer', str(index))
        self.assertEqual(len(self.handler._voice._seen), Constants.VOICE_NOTICE_IDS)

    def test_failed_metadata_send_keeps_inbox_action_visible(self) -> None:
        """A failed metadata request reports incomplete display without audio reads.

        Args:
            None
        Returns:
            None
        """
        self.ipc.send_command.side_effect = OSError('credential=private')
        self.handler._voice.request_inventory()
        self.assertIn(
            'metadata is unavailable', self.renderer.print_message.call_args.args[0]
        )
        self.assertNotIn(
            'credential=private', self.renderer.print_message.call_args.args[0]
        )
        self.assertEqual(self.handler._voice._pages_remaining, 0)

    def test_unrelated_responses_do_not_advance_or_cancel_scan(self) -> None:
        """Only the outstanding request may supply a page or fail it.

        Args:
            None
        Returns:
            None
        """
        self.handler._voice.request_inventory()
        first = self.ipc.send_command.call_args.args[0]
        self.handler.handle(
            RetainedMessagesEvent(
                messages=[self._entry('foreign')],
                next_cursor='wrong',
                request_id='other-request',
            )
        )
        self.handler.handle(RetainedMessagesUnavailableEvent(reason='stale'))
        self.handler.handle(
            RetainedMessagesUnavailableEvent(reason='stale', request_id='other-request')
        )
        self.assertEqual(self.ipc.send_command.call_count, 1)
        self.assertEqual(len(self.handler._voice._seen), 0)
        self.handler.handle(
            RetainedMessagesEvent(
                messages=[self._entry('mine')],
                next_cursor='next',
                request_id=first.request_id,
            )
        )
        second = self.ipc.send_command.call_args.args[0]
        self.assertEqual(second.cursor, 'next')
        self.assertNotEqual(first.request_id, second.request_id)
        self.handler.handle(
            RetainedMessagesEvent(
                messages=[self._entry('late')], request_id=first.request_id
            )
        )
        self.assertEqual(self.ipc.send_command.call_count, 2)
        self.assertEqual(len(self.handler._voice._seen), 1)
        self.handler.handle(
            RetainedMessagesUnavailableEvent(
                reason='stale', request_id=second.request_id
            )
        )
        self.handler.handle(
            RetainedMessagesEvent(
                messages=[self._entry('after')], request_id=second.request_id
            )
        )
        self.assertEqual(len(self.handler._voice._seen), 1)

    def test_stalled_inventory_can_be_replaced_by_a_later_request(self) -> None:
        """A lost metadata reply does not block a later explicit inbox scan.

        Args:
            None
        Returns:
            None
        """
        later = 1.0 + Constants.DEFAULT_IPC_TIMEOUT + 1.0
        with patch(
            'metor.ui.terminal.chat.event.voice.time.monotonic',
            side_effect=(1.0, later, later),
        ):
            self.handler._voice.request_inventory()
            first = self.ipc.send_command.call_args.args[0]
            self.handler._voice.request_inventory(target='peer.onion')
            second = self.ipc.send_command.call_args.args[0]
        self.assertNotEqual(first.request_id, second.request_id)
        self.assertEqual(second.target, 'peer.onion')
        self.handler.handle(
            RetainedMessagesEvent(
                messages=[self._entry('stale')], request_id=first.request_id
            )
        )
        self.assertEqual(len(self.handler._voice._seen), 0)

    def test_inbox_peer_scan_is_non_consuming_and_filters_metadata(self) -> None:
        """A text inbox response starts a bounded scan for that stable peer.

        Args:
            None
        Returns:
            None
        """
        dispatcher = CommandDispatcher(self.ipc, self.session, self.renderer)
        self.assertTrue(dispatcher.dispatch('/inbox peer'))
        self.assertIsInstance(self.ipc.send_command.call_args.args[0], MarkReadCommand)
        self.handler.handle(
            UnreadMessagesEvent(messages=[], alias='renamed', onion='peer.onion')
        )
        command = self.ipc.send_command.call_args.args[0]
        self.assertIsInstance(command, ListRetainedMessagesCommand)
        self.assertEqual(command.target, 'peer.onion')
        self.assertEqual(command.direction, MessageDirectionCode.IN)
        self.assertIsNone(command.delivery)
        wrong_peer = self._entry('wrong-peer')
        wrong_peer.onion = 'other.onion'
        text = self._entry('text')
        text.content_type = ContentType.TEXT
        incomplete = self._entry('incomplete')
        incomplete.finalized = False
        self.handler.handle(
            RetainedMessagesEvent(
                messages=[
                    wrong_peer,
                    text,
                    incomplete,
                    self._entry('out', MessageDirectionCode.OUT),
                    self._entry('drop'),
                ],
                request_id=command.request_id,
            )
        )
        self.assertEqual(len(self.handler._voice._seen), 1)
        self.assertEqual(self.ipc.send_command.call_count, 2)
        self.ipc.read_event.assert_not_called()
        self.ipc.request.assert_not_called()

    def test_peer_scan_waits_for_active_page_and_filters_delivery(self) -> None:
        """A peer lookup interrupts pagination without stealing another response.

        Args:
            None
        Returns:
            None
        """
        self.handler._voice.request_inventory()
        global_page = self.ipc.send_command.call_args.args[0]
        self.handler.handle(
            UnreadMessagesEvent(messages=[], alias='old', onion='peer.onion')
        )
        self.assertEqual(self.ipc.send_command.call_count, 1)
        self.handler.handle(
            RetainedMessagesEvent(next_cursor='more', request_id=global_page.request_id)
        )
        peer_page = self.ipc.send_command.call_args.args[0]
        self.assertEqual(peer_page.target, 'peer.onion')
        self.assertIsNone(peer_page.cursor)
        self.handler.handle(
            RetainedMessagesEvent(
                messages=[self._entry('unrelated')], request_id=global_page.request_id
            )
        )
        self.assertEqual(len(self.handler._voice._seen), 0)
        self.handler.handle(
            RetainedMessagesUnavailableEvent(
                reason='stale', request_id=peer_page.request_id
            )
        )
        self.handler._voice.request_inventory('peer.onion', Delivery.LIVE)
        filtered = self.ipc.send_command.call_args.args[0]
        self.assertEqual(filtered.delivery, Delivery.LIVE)
        self.assertEqual(filtered.target, 'peer.onion')
        self.handler.handle(
            RetainedMessagesEvent(
                messages=[self._entry('drop')], request_id=filtered.request_id
            )
        )
        self.assertEqual(len(self.handler._voice._seen), 0)

    def test_invalid_peer_response_clears_only_its_scan(self) -> None:
        """An invalid target cannot strand the queued peer inventory.

        Args:
            None
        Returns:
            None
        """
        self.handler._voice.request_inventory('gone.onion')
        first = self.ipc.send_command.call_args.args[0]
        self.handler._voice.request_inventory('current.onion')
        self.handler.handle(InvalidTargetEvent(target='elsewhere', request_id='other'))
        self.assertEqual(self.ipc.send_command.call_count, 1)
        self.handler.handle(
            InvalidTargetEvent(target='gone.onion', request_id=first.request_id)
        )
        second = self.ipc.send_command.call_args.args[0]
        self.assertEqual(second.target, 'current.onion')
        self.assertNotEqual(first.request_id, second.request_id)

    def test_multiple_inbox_peers_keep_their_own_correlated_scans(self) -> None:
        """Queued peer requests survive another peer's paginated lookup.

        Args:
            None
        Returns:
            None
        """
        self.handler._voice.request_inventory()
        global_page = self.ipc.send_command.call_args.args[0]
        for onion in ('first.onion', 'second.onion'):
            self.handler.handle(
                UnreadMessagesEvent(messages=[], alias='peer', onion=onion)
            )
        self.handler.handle(
            RetainedMessagesEvent(next_cursor='more', request_id=global_page.request_id)
        )
        first = self.ipc.send_command.call_args.args[0]
        self.assertEqual(first.target, 'first.onion')
        self.handler.handle(
            RetainedMessagesEvent(next_cursor='next', request_id=first.request_id)
        )
        first_next = self.ipc.send_command.call_args.args[0]
        self.assertEqual(first_next.target, 'first.onion')
        self.handler.handle(RetainedMessagesEvent(request_id=first_next.request_id))
        second = self.ipc.send_command.call_args.args[0]
        self.assertEqual(second.target, 'second.onion')
        self.assertIsNone(second.cursor)
        self.handler.handle(RetainedMessagesEvent(request_id=second.request_id))
        self.assertEqual(self.ipc.send_command.call_count, 4)

    def test_dedupe_uses_onion_after_alias_rename(self) -> None:
        """An alias-only notification matches a previously seen stable peer.

        Args:
            None
        Returns:
            None
        """
        self.session.remember_peer('old', 'peer.onion')
        self.handler._voice.announce(None, 'peer.onion', 'old', 'id')
        self.session.remember_peer('new', 'peer.onion')
        self.assertTrue(self.handler._voice.seen(None, None, 'new', 'id'))
        self.assertFalse(self.handler._voice.announce(None, None, 'new', 'id'))
        self.renderer.print_message.assert_called_once()


if __name__ == '__main__':
    unittest.main()
