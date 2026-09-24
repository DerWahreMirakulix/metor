"""Exact local DROP cleanup through GUI coordination and real encrypted Core IPC."""

from dataclasses import replace
import unittest
from unittest.mock import Mock, patch

import test_gui_producers as support
from test_gui_contacts import address
from metor.client import FrontendProfileState
from metor.client import FrontendLaunchContext
from metor.core.api import (
    ContentType,
    Delivery,
    DeleteMessageCommand,
    ClearMessagesCommand,
    GetGuiPreferencesCommand,
    GuiPreferencesEvent,
    MessageDirectionCode,
    MessageStatusCode,
    SetGuiPreferencesCommand,
)
from metor.data import MessageDirection, MessageStatus
from metor.ui.gui.runtime import GuiController, conversation_rows
from metor.ui.gui.runtime.transcript import TranscriptItem
from metor.ui.gui.state import Route
from metor.ui.gui.state.media import PlaybackTarget


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


if __name__ == '__main__':
    unittest.main()
