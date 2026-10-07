"""Exact local DROP cleanup through GUI coordination and real encrypted Core IPC."""

from dataclasses import replace
import threading
import unittest
from unittest.mock import Mock, patch

import test_gui_producers as support
from test_gui_contacts import address
from metor.client import FrontendProfileState
from metor.client import FrontendLaunchContext, MetorClient, build_session_auth_proof
from metor.core.api import (
    ContentType,
    Delivery,
    DeleteMessageCommand,
    ClearMessagesCommand,
    GetGuiPreferencesCommand,
    GetMessagesCommand,
    GetMessageOutcomeCommand,
    GuiPreferencesEvent,
    IpcEvent,
    MessageEntry,
    MessageOutcomeEvent,
    MessageDirectionCode,
    MessageStatusCode,
    MessagesDataEvent,
    RuntimeStateChangedEvent,
    SetGuiPreferencesCommand,
    TextContent,
    VoiceContent,
)
from metor.data import MessageDirection, MessageStatus
from metor.ui.gui.runtime import GuiController, conversation_rows
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.runtime.transcript import TranscriptItem
from metor.ui.gui.state import Route
from metor.ui.gui.state.media import PlaybackTarget
from metor.ui.gui.state.mailbox import Update


class DropCoreTests(unittest.TestCase):
    """Exercises actual persistence, producer isolation and direction-qualified GUI cleanup."""

    def setUp(self) -> None:
        """Creates an isolated protected runtime with an authorized GUI SDK connection.

        Args:
            None
        Returns:
            None
        """
        self.h = support.GuiProducerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.h.onion = address(17)
        self.h.contacts.ensure_alias_for_onion(self.h.onion)
        self.gui = GuiController(
            FrontendLaunchContext(
                'voice-owned',
                Mock(
                    profile_state=lambda: FrontendProfileState(
                        'voice-owned', True, False, False
                    )
                ),
            )
        )
        self.addCleanup(self.gui.close)
        self.gui.client = self.h.client
        self.gui.state.snapshot = self.h.client.runtime_snapshot()
        self.gui.state.capabilities = frozenset(self.h.client.init_event.capabilities)
        self.gui.state.preferences = self.h.client.request(
            GetGuiPreferencesCommand(), GuiPreferencesEvent
        )
        self.gui.state.covered = False
        self.gui.state.route = Route('V06')

    def item(
        self, identity: str, direction: MessageDirection, status: MessageStatus
    ) -> None:
        """Adds genuine retained text through the Core storage owner for the test fixture.

        Args:
            identity: Stable fixture message ID.
            direction: Explicit inbound/outbound fixture identity.
            status: Authoritative fixture receipt state.
        Returns:
            None
        """
        self.h.messages.queue_message(
            self.h.onion,
            direction,
            Delivery.DROP,
            ContentType.TEXT,
            '{"text":"fixture"}',
            status,
            identity,
        )
        self.gui.transcript.admit(
            TranscriptItem(
                self.h.onion,
                Delivery.DROP,
                MessageDirectionCode(direction.value),
                identity,
                'fixture',
                status=MessageStatusCode(status.value),
            )
        )

    def settle(self) -> None:
        """Drains admitted asynchronous GUI work and its authoritative refresh.

        Args:
            None
        Returns:
            None
        """
        for _ in range(8):
            if self.gui._worker is not None:
                self.gui._worker.join(5)
            self.gui.poll()
            if (
                not self.gui.state.busy
                and self.gui.drop.pending is None
                and not self.gui.receipts.busy
            ):
                break
        self.assertIsNone(self.gui.drop.pending)
        self.assertFalse(self.gui.receipts.busy)

    def _external_archive_change(self, *, hidden: bool, clear: bool) -> None:
        """Receives a second client's genuine Core mutation while a GUI read is blocked."""
        changed = threading.Event()

        def observe(event: IpcEvent) -> None:
            """Relays actual Core broadcasts through the production GUI mailbox."""
            self.gui.mailbox.put(Update(self.gui.state.generation, 'event', event))
            if (
                isinstance(event, RuntimeStateChangedEvent)
                and event.scope == 'messages'
            ):
                changed.set()

        provider = Mock()
        provider.get_session_auth_proof.side_effect = lambda challenge, salt: (
            build_session_auth_proof('test-password', challenge, salt)
        )
        observer = MetorClient(
            self.h.daemon._ipc.port, auth_provider=provider, on_event=observe
        )
        self.addCleanup(observer.disconnect)
        self.assertIsNotNone(observer.bootstrap())
        self.gui.client = observer
        self.item('known-drop', MessageDirection.IN, MessageStatus.UNREAD)
        self.item('pending', MessageDirection.OUT, MessageStatus.PENDING)
        self.gui.state.route = Route('V08', self.h.onion, Delivery.DROP)
        self.gui.messages = observer.request(
            GetMessagesCommand(self.h.onion), MessagesDataEvent
        )
        self.gui.transcript.discard(
            self.h.onion, Delivery.DROP, 'pending', MessageDirectionCode.OUT
        )
        if hidden:
            self.gui.navigate(Route('V09', self.h.onion, Delivery.LIVE))
        release = threading.Event()
        self.addCleanup(release.set)

        def held_read() -> None:
            """Holds the bounded read lane while the external command and GUI event complete."""
            if not release.wait(5):
                raise TimeoutError('External-change fixture read was not released')

        self.assertTrue(self.gui.submit('held-read', held_read, background=True))
        reader = self.gui._worker
        assert reader is not None
        command = (
            ClearMessagesCommand()
            if clear
            else DeleteMessageCommand(
                self.h.onion, 'known-drop', MessageDirectionCode.IN
            )
        )
        self.assertIsNotNone(self.h.other.request(command, IpcEvent))
        self.assertTrue(changed.wait(5))
        self.gui.poll()
        if hidden:
            self.gui.navigate(Route('V08', self.h.onion, Delivery.DROP))
            self.assertEqual(
                [row.msg_id for row in self.gui.messages.messages], ['pending']
            )
            self.assertNotIn(
                (self.h.onion, Delivery.DROP, MessageDirectionCode.IN, 'known-drop'),
                self.gui.transcript.items,
            )
        release.set()
        reader.join(5)
        expected_archive = set() if clear else {'pending'}
        for _ in range(16):
            self.gui.poll()
            if self.gui._worker is not None:
                self.gui._worker.join(5)
            if (
                self.gui.messages is not None
                and {row.msg_id for row in self.gui.messages.messages}
                == expected_archive
                and not self.gui.receipts.busy
                and not self.gui.archive.loading
                and self.gui.inventory.page is not None
                and any(
                    item.msg_id == 'pending'
                    for item in self.gui.inventory.page.messages
                )
            ):
                break
        self.assertIsNotNone(self.gui.messages)
        self.assertEqual(
            {row.msg_id for row in self.gui.messages.messages}, expected_archive
        )
        self.assertIsNotNone(self.gui.inventory.page)
        self.assertIn(
            'pending', {item.msg_id for item in self.gui.inventory.page.messages}
        )
        self.assertNotIn(
            (self.h.onion, Delivery.DROP, MessageDirectionCode.IN, 'known-drop'),
            self.gui.transcript.items,
        )
        current = self.h.other.request(
            GetMessagesCommand(self.h.onion), MessagesDataEvent
        )
        self.assertEqual({row.msg_id for row in current.messages}, expected_archive)
        pending = self.h.other.request(
            GetMessageOutcomeCommand(self.h.onion, 'pending', MessageDirectionCode.OUT),
            MessageOutcomeEvent,
        )
        self.assertEqual(pending.status, MessageStatusCode.PENDING)

    def test_external_delete_revokes_hidden_drop_before_return_frame(self) -> None:
        """A GUI in LIVE cannot resurrect another client's deleted archive body on return."""
        self._external_archive_change(hidden=True, clear=False)

    def test_external_clear_preserves_page_only_pending_drop_on_return(self) -> None:
        """Unqualified external clear revokes hidden eligible rows while Core pending remains."""
        self._external_archive_change(hidden=True, clear=True)

    def test_external_delete_reconciles_visible_transcript_without_resurrection(
        self,
    ) -> None:
        """Fresh archive reads and exact receipt proof also remove a visible duplicate body."""
        self._external_archive_change(hidden=False, clear=False)

    def test_first_text_drop_appears_in_open_archive_without_live_connection(
        self,
    ) -> None:
        """The production send/result/poll path updates the same route and clears its draft."""
        route = Route('V08', self.h.onion, Delivery.DROP)
        self.gui.navigate(route)
        self.gui.state.set_draft(self.h.onion, Delivery.DROP, 'first drop')
        for _ in range(12):
            if self.gui._worker is not None:
                self.gui._worker.join(5)
            self.gui.poll()
        self.assertFalse(self.gui.state.busy)
        self.assertFalse(self.gui.state.snapshot.live_contexts)
        self.gui.send_text(self.h.onion, Delivery.DROP)
        for _ in range(12):
            if self.gui._worker is not None:
                self.gui._worker.join(5)
            self.gui.poll()
            if self.gui.messages is not None and self.gui.messages.messages:
                break
        self.assertEqual(self.gui.state.route, route)
        self.assertNotIn((self.h.onion, Delivery.DROP), self.gui.state.drafts)
        self.assertIsNotNone(self.gui.messages)
        self.assertEqual(len(self.gui.messages.messages), 1)
        self.assertEqual(self.gui.messages.messages[0].content.text, 'first drop')

    def test_sending_from_older_history_returns_to_confirmed_newest_drop(self) -> None:
        """Actual Core acceptance refreshes the latest page instead of reusing its old cursor."""
        self.item('older', MessageDirection.IN, MessageStatus.READ)
        self.item('more-recent', MessageDirection.IN, MessageStatus.READ)
        route = Route('V08', self.h.onion, Delivery.DROP)
        self.gui.navigate(route)
        for _ in range(12):
            if self.gui._worker is not None:
                self.gui._worker.join(5)
            self.gui.poll()
        self.gui.archive.before = MessageDirectionCode.IN, 'more-recent'
        self.gui.archive.needed = True
        for _ in range(12):
            if self.gui._worker is not None:
                self.gui._worker.join(5)
            self.gui.poll()
        self.assertEqual(
            [item.msg_id for item in self.gui.messages.messages], ['older']
        )
        self.gui.state.set_draft(self.h.onion, Delivery.DROP, 'new from older history')
        self.gui.send_text(self.h.onion, Delivery.DROP)
        for _ in range(12):
            if self.gui._worker is not None:
                self.gui._worker.join(5)
            self.gui.poll()
            if self.gui.messages is not None and any(
                item.content.text == 'new from older history'
                for item in self.gui.messages.messages
            ):
                break
        self.assertEqual(self.gui.state.route, route)
        self.assertIsNone(self.gui.archive.before)
        self.assertNotIn((self.h.onion, Delivery.DROP), self.gui.state.drafts)
        self.assertFalse(self.gui.state.snapshot.live_contexts)
        self.assertIn(
            'new from older history',
            [item.content.text for item in self.gui.messages.messages],
        )

    def test_archive_handoff_releases_pending_ui_copy_and_uses_core_receipt(
        self,
    ) -> None:
        """A real stored Delivered row replaces cached Pending without deleting durable text."""
        self.h.messages.queue_message(
            self.h.onion,
            MessageDirection.OUT,
            Delivery.DROP,
            ContentType.TEXT,
            'confirmed body',
            MessageStatus.DELIVERED,
            'archived-confirmed',
        )
        self.assertTrue(
            self.gui.transcript.admit(
                TranscriptItem(
                    self.h.onion,
                    Delivery.DROP,
                    MessageDirectionCode.OUT,
                    'archived-confirmed',
                    'confirmed body',
                    status=MessageStatusCode.PENDING,
                )
            )
        )
        self.gui.navigate(Route('V08', self.h.onion, Delivery.DROP))
        for _ in range(12):
            if self.gui._worker is not None:
                self.gui._worker.join(5)
            self.gui.poll()
            if self.gui.messages is not None and self.gui.messages.messages:
                break
        self.assertIsNotNone(self.gui.messages)
        row = self.gui.messages.messages[0]
        self.assertEqual(row.msg_id, 'archived-confirmed')
        self.assertEqual(row.status, MessageStatusCode.DELIVERED)
        self.assertEqual(row.content.text, 'confirmed body')
        self.assertFalse(self.gui.transcript.items)
        records = self.h.messages.get_chat_history(self.h.onion)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].msg_id, 'archived-confirmed')
        self.assertEqual(records[0].payload, 'confirmed body')

    def test_lost_delete_result_reads_archive_presence_with_exact_direction(
        self,
    ) -> None:
        """A lost actual deletion result removes only the positively absent original archive copy.

        Args:
            None
        Returns:
            None
        """
        self.item('shared', MessageDirection.IN, MessageStatus.UNREAD)
        self.item('shared', MessageDirection.OUT, MessageStatus.PENDING)
        original = self.h.client.request
        mutations = []

        def lost(command: object, expected: object) -> object:
            """Drops only the real delete acknowledgement; all reads use actual Core.

            Args:
                command: Actual production command.
                expected: Public response type.
            Returns:
                object: Actual read result, or missing mutation receipt.
            """
            result = original(command, expected)
            if isinstance(command, DeleteMessageCommand):
                mutations.append(command)
                return None
            return result

        with patch.object(self.h.client, 'request', side_effect=lost):
            self.assertTrue(
                self.gui.drop.delete(self.h.onion, 'shared', MessageDirectionCode.IN)
            )
            self.settle()
        self.assertEqual(len(mutations), 1)
        self.assertEqual(
            {key[2] for key in self.gui.transcript.items}, {MessageDirectionCode.OUT}
        )
        self.assertEqual(len(self.h.messages.get_pending_outbox()), 1)

    def test_lost_clear_reads_only_preexisting_targets_and_keeps_pending_delivery(
        self,
    ) -> None:
        """Readback of uncertain cleanup does not sweep a later arrival or a protected owner draft.

        Args:
            None
        Returns:
            None
        """
        self.item('before', MessageDirection.IN, MessageStatus.UNREAD)
        self.item('pending', MessageDirection.OUT, MessageStatus.PENDING)
        self.h.capture('review')
        original = self.h.client.request
        mutations = []

        def lost(command: object, expected: object) -> object:
            """Executes clear once and hides only its actual response.

            Args:
                command: Actual production request.
                expected: Public response type.
            Returns:
                object: Actual readback or missing clear receipt.
            """
            result = original(command, expected)
            if isinstance(command, ClearMessagesCommand):
                mutations.append(command)
                return None
            return result

        with patch.object(self.h.client, 'request', side_effect=lost):
            self.assertTrue(self.gui.drop.clear(self.h.onion))
            self.gui._worker.join(5)
            self.item('after', MessageDirection.IN, MessageStatus.UNREAD)
            self.settle()
        self.assertEqual(len(mutations), 1)
        self.assertEqual(
            [item.msg_id for item in self.gui.transcript.items.values()], ['after']
        )
        self.assertEqual(len(self.h.messages.get_pending_outbox()), 1)
        self.assertIsNotNone(self.h.repository.get('review'))

    def test_direction_qualified_delete_preserves_same_id_outbound_pending(
        self,
    ) -> None:
        """Inbound deletion cannot erase the outbound identity or cancel its delivery.

        Args:
            None
        Returns:
            None
        """
        self.item('shared', MessageDirection.IN, MessageStatus.UNREAD)
        self.item('shared', MessageDirection.OUT, MessageStatus.PENDING)
        self.assertTrue(
            self.gui.drop.delete(self.h.onion, 'shared', MessageDirectionCode.IN)
        )
        self.settle()
        records = self.h.messages.get_chat_history(self.h.onion)
        self.assertEqual(
            [(row.msg_id, row.direction) for row in records], [('shared', 'out')]
        )
        self.assertEqual(
            {key[2] for key in self.gui.transcript.items}, {MessageDirectionCode.OUT}
        )
        self.assertTrue(
            self.gui.drop.delete(self.h.onion, 'shared', MessageDirectionCode.OUT)
        )
        self.settle()
        self.assertEqual(self.gui.state.status, 'Pending delivery is preserved')
        self.assertEqual(len(self.gui.transcript.items), 1)

    def test_clear_unpins_but_preserves_pending_and_owner_review(self) -> None:
        """A confirmed clear drops only published local history and its GUI media copies.

        Args:
            None
        Returns:
            None
        """
        self.item('pending', MessageDirection.OUT, MessageStatus.PENDING)
        self.item('received', MessageDirection.IN, MessageStatus.UNREAD)
        self.h.capture('review')
        self.h.client.finalize_voice('review', owner_token=self.h.owner)
        current = self.gui.state.preferences
        self.h.client.request(
            SetGuiPreferencesCommand(
                expected_revision=current.preferences_revision,
                preferences=replace(current.preferences, pins=[self.h.onion]),
            ),
            GuiPreferencesEvent,
        )
        self.gui.transcript.admit(
            TranscriptItem(
                self.h.onion, Delivery.LIVE, MessageDirectionCode.IN, 'live', 'consumed'
            )
        )
        target = PlaybackTarget(
            0,
            'profile',
            'epoch',
            self.h.onion,
            Delivery.DROP,
            MessageDirectionCode.IN,
            'received',
        )
        review = replace(
            target,
            msg_id='review',
            direction=MessageDirectionCode.OUT,
            owner_token=self.h.owner,
        )
        live = replace(target, msg_id='live', delivery=Delivery.LIVE)
        for entry in (target, review, live):
            self.assertTrue(
                self.gui.playback.cache.append(entry, 0, b'\x00\x01', complete=True)
            )
        self.assertTrue(self.gui.drop.clear(self.h.onion))
        self.settle()
        self.assertIsNone(self.gui.playback.cache.read(target, 0, 2))
        self.assertIsNotNone(self.gui.playback.cache.read(review, 0, 2))
        self.assertIsNotNone(self.gui.playback.cache.read(live, 0, 2))
        self.assertFalse(
            self.gui.playback.cache.append(target, 0, b'\x00\x01', complete=True)
        )
        self.assertEqual(
            [item.msg_id for item in self.gui.transcript.items.values()], ['live']
        )
        self.assertIsNotNone(
            self.h.messages.get_voice_payload(
                self.h.onion, 'review', MessageDirection.OUT
            )
        )
        self.assertIsNotNone(self.h.repository.get('review'))
        self.assertEqual(
            self.h.client.request(
                GetGuiPreferencesCommand(), GuiPreferencesEvent
            ).preferences.pins,
            [],
        )
        self.gui.state.snapshot = self.h.client.runtime_snapshot()
        rows = conversation_rows(self.gui, Delivery.DROP)
        self.assertEqual(
            [(row.peer, row.pending, row.unseen) for row in rows],
            [(self.h.onion, 1, 0)],
        )


class DropArchivePresentationTests(unittest.TestCase):
    """Bounded duplicate presentation is released only by an exact available Core text row."""

    def setUp(self) -> None:
        """Creates an inert controller with an exact current DROP archive request."""
        self.gui = GuiController(
            FrontendLaunchContext('fixture', Mock()), simulator=True
        )
        self.addCleanup(self.gui.close)
        self.peer = 'archive-peer'
        self.gui.state.covered = False
        self.gui.state.route = Route('V08', self.peer, Delivery.DROP)
        self.operation = 'archive:1:' + self.peer
        self.gui.archive._operation = self.operation

    def cached(
        self,
        identity: str,
        *,
        peer: str | None = None,
        delivery: Delivery = Delivery.DROP,
        direction: MessageDirectionCode = MessageDirectionCode.OUT,
        status: MessageStatusCode = MessageStatusCode.PENDING,
        text: str | None = 'confirmed',
    ) -> None:
        """Admits one confirmed runtime copy under its full message identity."""
        self.assertTrue(
            self.gui.transcript.admit(
                TranscriptItem(
                    peer or self.peer,
                    delivery,
                    direction,
                    identity,
                    text=text,
                    status=status,
                )
            )
        )

    def install(self, entries: list[MessageEntry], **fields: object) -> None:
        """Installs one typed page through the actual exact archive owner."""
        event = MessagesDataEvent(entries, 'archive', self.peer, **fields)
        self.gui.archive._operation = self.operation
        self.assertTrue(
            self.gui.archive.install(
                Update(self.gui.state.generation, self.operation, event)
            )
        )

    def row(
        self, identity: str, status: MessageStatusCode = MessageStatusCode.DELIVERED
    ) -> MessageEntry:
        """Returns one positively stored outgoing text row."""
        return MessageEntry(
            MessageDirectionCode.OUT,
            status,
            Delivery.DROP,
            TextContent('confirmed'),
            'timestamp',
            identity,
        )

    def test_current_actual_text_releases_only_matching_published_own_identity(
        self,
    ) -> None:
        """Metadata, absent rows, drafts, other peers and directions do not release recent text."""
        self.cached('matched')
        self.cached('recent')
        self.cached('matched', direction=MessageDirectionCode.IN)
        self.cached('matched', delivery=Delivery.LIVE)
        self.cached('matched', peer='other-peer')
        self.cached('voice', text=None)
        self.cached('review', status=MessageStatusCode.DRAFT)
        self.cached('missing-id')
        self.install([])
        self.assertEqual(len(self.gui.transcript.items), 8)
        rows = [
            self.row('matched'),
            self.row('review', MessageStatusCode.DRAFT),
            replace(self.row('voice'), content=VoiceContent('blob', 'codec', 1)),
            replace(self.row('missing-id'), msg_id=None),
        ]
        self.install(rows)
        self.assertEqual(len(self.gui.transcript.items), 7)
        self.assertNotIn(
            (self.peer, Delivery.DROP, MessageDirectionCode.OUT, 'matched'),
            self.gui.transcript.items,
        )
        self.assertEqual(
            self.gui.messages.messages[0].status, MessageStatusCode.DELIVERED
        )
        self.assertIn(
            (self.peer, Delivery.DROP, MessageDirectionCode.OUT, 'recent'),
            self.gui.transcript.items,
        )

    def test_unavailable_wrong_request_and_invalidated_read_retain_recent_row(
        self,
    ) -> None:
        """Only the current available page can release a recent confirmed copy."""
        self.cached('recent')
        self.install([self.row('recent')], page_available=False)
        event = MessagesDataEvent([self.row('recent')], 'archive', self.peer)
        self.gui.archive.install(
            Update(self.gui.state.generation, 'archive:old', event)
        )
        self.gui._operations.invalidate_reads()
        self.gui.archive._operation = self.operation
        self.gui.archive.install(
            Update(self.gui.state.generation, self.operation, event, read_epoch=0)
        )
        self.assertEqual(len(self.gui.transcript.items), 1)
        self.assertTrue(self.gui.archive.needed)
        self.install([self.row('recent')])
        self.assertFalse(self.gui.transcript.items)

    def test_matching_archive_preserves_more_advanced_cached_read_receipt(self) -> None:
        """Cache release retains a known Read receipt when the archive reply was captured earlier."""
        self.cached('recent', status=MessageStatusCode.READ)
        self.install([self.row('recent')])
        self.assertFalse(self.gui.transcript.items)
        self.assertEqual(self.gui.messages.messages[0].status, MessageStatusCode.READ)

    def test_held_archive_does_not_downgrade_visible_receipts_after_cache_handoff(
        self,
    ) -> None:
        """Archived positive receipts survive an older reply after runtime copies are gone."""
        self.install(
            [
                self.row('read', MessageStatusCode.READ),
                self.row('delivered', MessageStatusCode.DELIVERED),
                replace(
                    self.row('inbound-read', MessageStatusCode.READ),
                    direction=MessageDirectionCode.IN,
                ),
            ]
        )
        self.assertFalse(self.gui.transcript.items)
        self.install(
            [
                self.row('read', MessageStatusCode.PENDING),
                self.row('delivered', MessageStatusCode.PENDING),
                replace(
                    self.row('inbound-read', MessageStatusCode.UNREAD),
                    direction=MessageDirectionCode.IN,
                ),
            ]
        )
        self.assertEqual(
            [entry.status for entry in self.gui.messages.messages],
            [
                MessageStatusCode.READ,
                MessageStatusCode.DELIVERED,
                MessageStatusCode.READ,
            ],
        )

    def test_many_confirmed_archived_rows_restore_bounded_presentation_capacity(
        self,
    ) -> None:
        """Repeated confirmed DROPs do not permanently exhaust the runtime transcript budget."""
        for index in range(GuiLimits.LIVE_ITEMS):
            self.cached('confirmed-' + str(index))
        self.assertEqual(self.gui.transcript.capacity()[0], 0)
        self.assertFalse(
            self.gui.transcript.admit(
                TranscriptItem(
                    self.peer,
                    Delivery.DROP,
                    MessageDirectionCode.OUT,
                    'next',
                    'confirmed',
                )
            )
        )
        for offset in range(0, GuiLimits.LIVE_ITEMS, GuiLimits.PAGE_ITEMS):
            self.install(
                [
                    self.row('confirmed-' + str(index))
                    for index in range(
                        offset, min(offset + GuiLimits.PAGE_ITEMS, GuiLimits.LIVE_ITEMS)
                    )
                ]
            )
        self.assertFalse(self.gui.transcript.items)
        self.assertEqual(self.gui.transcript.bytes, 0)
        self.assertEqual(self.gui.transcript.capacity()[0], GuiLimits.LIVE_ITEMS)
        self.cached('next')


if __name__ == '__main__':
    unittest.main()
