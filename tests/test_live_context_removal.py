"""Real protected Core removal keeps durable cancellation exact and compatible."""

import unittest

import test_gui_producers as support
from metor.core.api import (
    ConfigUpdatedEvent,
    ContentType,
    Delivery,
    DismissLiveContextCommand,
    IpcEvent,
    LiveContextDismissedEvent,
    LiveContextDismissRejectedEvent,
    MessageOperationReason,
    SetConfigCommand,
)
from metor.data import MessageDirection, MessageStatus, SettingKey


class LiveContextRemovalTests(unittest.TestCase):
    """Exercises actual storage, SDK and IPC without Tor or audio hardware."""

    def setUp(self) -> None:
        """Creates one isolated authorized daemon and a second exact peer."""
        self.h = support.GuiProducerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.peer = self.h.onion
        self.other_peer = 'c' * len(self.peer)
        self.h.contacts.ensure_alias_for_onion(self.other_peer)

    def queue(
        self,
        peer: str,
        msg_id: str,
        *,
        direction: MessageDirection = MessageDirection.OUT,
        delivery: Delivery = Delivery.LIVE,
    ) -> None:
        """Persists a canonical text message under the requested exact identity."""
        self.h.messages.queue_message(
            peer,
            direction,
            delivery,
            ContentType.TEXT,
            '{"text":"fixture"}',
            MessageStatus.PENDING
            if direction is MessageDirection.OUT
            else MessageStatus.UNREAD,
            msg_id,
        )

    def test_default_dismiss_retains_pending_and_explicit_cancel_keeps_unknown_receipt(
        self,
    ) -> None:
        """Legacy dismissal rejects work; explicit cancellation clears only the exact LIVE peer."""
        self.queue(self.peer, 'same')
        self.queue(self.peer, 'received', direction=MessageDirection.IN)
        self.queue(self.other_peer, 'same')
        self.queue(self.peer, 'drop', delivery=Delivery.DROP)
        state = self.h.daemon._transport_state
        generation = state.live_generation(self.peer, 'same')
        other_generation = state.live_generation(self.other_peer, 'same')
        state.add_unacked_message(self.peer, 'same', 'fixture', 'timestamp')
        state.remember_message_request_id(
            'same', 'other-request', live_peer=self.other_peer
        )
        legacy = self.h.client.request(DismissLiveContextCommand(self.peer), IpcEvent)
        self.assertIsInstance(legacy, LiveContextDismissRejectedEvent)
        self.assertEqual(legacy.reason, MessageOperationReason.OUTBOUND_PENDING_LIVE)
        self.assertTrue(state.is_live_generation(self.peer, 'same', generation))
        result = self.h.client.request(
            DismissLiveContextCommand(self.peer, True), IpcEvent
        )
        self.assertIsInstance(result, LiveContextDismissedEvent)
        self.assertFalse(state.is_live_generation(self.peer, 'same', generation))
        self.assertTrue(
            state.is_live_generation(self.other_peer, 'same', other_generation)
        )
        self.assertEqual(state.pop_message_request_id('same'), 'other-request')
        self.assertEqual(self.h.messages.get_pending_live_outbox(self.peer), [])
        self.assertEqual(self.h.messages.get_unread_live_count(self.peer), 0)
        self.assertEqual(
            [
                row.msg_id
                for row in self.h.messages.get_pending_live_outbox(self.other_peer)
            ],
            ['same'],
        )
        self.assertEqual(
            [row.msg_id for row in self.h.messages.get_chat_history(self.peer)],
            ['drop'],
        )
        self.assertIsNone(self.h.messages.mark_live_text_delivered(self.peer, 'same'))
        self.assertEqual(
            self.h.messages.message_state(self.peer, 'same', MessageDirection.OUT),
            (Delivery.LIVE, MessageStatus.PENDING, False),
        )

    def test_discard_selection_rejects_stale_and_cross_peer_without_partial_changes(
        self,
    ) -> None:
        """A stale or misqualified selection cannot clear any valid pending payload."""
        self.queue(self.peer, 'first')
        self.queue(self.peer, 'second')
        self.queue(self.other_peer, 'other')
        for selected in (['first', 'missing'], ['first', 'other'], ['first', 'first']):
            self.assertIsNone(self.h.messages.discard_pending_live(self.peer, selected))
            self.assertEqual(
                {
                    row.msg_id
                    for row in self.h.messages.get_pending_live_outbox(self.peer)
                },
                {'first', 'second'},
            )

    def test_accepted_recovery_refuses_discard_and_preserves_queued_generation(
        self,
    ) -> None:
        """An accepted scope remains protected even without a current transport socket."""
        self.queue(self.peer, 'first')
        state = self.h.daemon._transport_state
        generation = state.live_generation(self.peer, 'first')
        with state.snapshot_barrier():
            state._accepted_live_contexts[self.peer] = 1
        result = self.h.client.request(
            DismissLiveContextCommand(self.peer, True), IpcEvent
        )
        self.assertIsInstance(result, LiveContextDismissRejectedEvent)
        self.assertEqual(result.reason, MessageOperationReason.ACTIVE_LIVE_CONTEXT)
        self.assertTrue(state.is_live_generation(self.peer, 'first', generation))
        self.assertEqual(
            [row.msg_id for row in self.h.messages.get_pending_live_outbox(self.peer)],
            ['first'],
        )
        state.revoke_accepted_live_context(self.peer)

    def test_shutdown_finalizes_dormant_pending_only_when_existing_policy_enabled(
        self,
    ) -> None:
        """Network teardown reaches durable pending work without requiring an active socket."""
        self.queue(self.peer, 'dormant')
        self.h.client.request(
            SetConfigCommand(SettingKey.FALLBACK_TO_DROP.value, False),
            ConfigUpdatedEvent,
        )
        self.h.daemon._network.disconnect_all()
        self.assertEqual(
            [row.msg_id for row in self.h.messages.get_pending_live_outbox(self.peer)],
            ['dormant'],
        )
        self.h.client.request(
            SetConfigCommand(SettingKey.FALLBACK_TO_DROP.value, True),
            ConfigUpdatedEvent,
        )
        self.h.daemon._network.disconnect_all()
        self.assertEqual(self.h.messages.get_pending_live_outbox(self.peer), [])
        self.assertEqual(
            [row.msg_id for row in self.h.messages.get_chat_history(self.peer)],
            ['dormant'],
        )


if __name__ == '__main__':
    unittest.main()
