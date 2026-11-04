"""LIVE fallback identity and dismissal preservation through actual protected Core IPC."""

import unittest
from unittest.mock import Mock, patch

import test_gui_producers as support
from metor.client import FrontendProfileState
from metor.client import FrontendLaunchContext
from metor.core.api import (
    ContentType,
    ConnectedEvent,
    ConnectionActor,
    ConnectionAutoAcceptedEvent,
    ConnectionConnectingEvent,
    ConnectionFailedEvent,
    ConnectionReasonCode,
    ConnectionRejectedEvent,
    ContactEntry,
    Delivery,
    FallbackCommand,
    LiveContextEntry,
    MessageDirectionCode,
    MessageStatusCode,
    RuntimeSnapshotEvent,
    RetunnelInitiatedEvent,
)
from metor.data import MessageDirection, MessageStatus
from metor.ui.gui.runtime import GuiController, conversation_rows
from metor.ui.gui.runtime.live import LiveMutation, pending_fallback_count
from metor.ui.gui.runtime.transcript import TranscriptItem
from metor.ui.gui.runtime.voice.press import CaptureBinding, PressSource
from metor.ui.gui.state import Route
from metor.ui.gui.state.media import PlaybackTarget
from metor.ui.gui.state.mailbox import Update


class LiveStatusPresentationTests(unittest.TestCase):
    """Transport progress belongs to the persistent conversation header only."""

    def test_successful_start_and_route_change_do_not_publish_action_feedback(
        self,
    ) -> None:
        """Acknowledged progress refreshes Core state without duplicating status as a toast."""
        gui = GuiController(FrontendLaunchContext('fixture', Mock()), simulator=True)
        gui.state.covered = False
        gui.refresh_state = Mock()
        for kind, event in (
            ('start', ConnectionConnectingEvent('Bob', 'bob')),
            ('route', RetunnelInitiatedEvent('Bob', 'bob')),
        ):
            with self.subTest(kind=kind):
                gui.live.pending = LiveMutation('live:fixture', 'bob', kind)
                before = gui.state.feedback.revision
                self.assertTrue(gui.live.install(Update(0, 'live:fixture', event)))
                self.assertIsNone(gui.live.pending)
                self.assertEqual(gui.state.feedback.revision, before)
        self.assertEqual(gui.refresh_state.call_count, 2)


class LiveStartPresentationTests(unittest.TestCase):
    """Explicit starts respond before IPC and keep failures separate from progress."""

    def setUp(self) -> None:
        """Creates a controlled result boundary with real GUI presentation ownership."""
        self.gui = GuiController(
            FrontendLaunchContext('fixture', Mock()), simulator=True
        )
        self.gui.state.covered = False
        self.gui.state.route = Route('V09', 'bob', Delivery.LIVE)
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture', 'self', contacts=[ContactEntry('Bob', 'bob')], revision=4
        )
        self.gui.client = Mock()
        self.gui.submit = Mock(return_value=True)
        self.gui.refresh_state = Mock()

    def acknowledge(self) -> None:
        """Installs the correlated admission result without a transport snapshot."""
        mutation = self.gui.live.pending
        self.assertIsNotNone(mutation)
        self.gui.live.install(
            Update(0, mutation.operation, ConnectionConnectingEvent('Bob', 'bob'))
        )

    def test_start_is_immediate_and_old_snapshot_cannot_reenable_duplicate(
        self,
    ) -> None:
        """Local request admission bridges the full wait for an authoritative attempt."""
        before = self.gui.state.feedback.revision
        self.assertTrue(self.gui.live.start('bob'))
        self.assertTrue(self.gui.live.starting('bob'))
        self.assertFalse(self.gui.live.start('bob'))
        self.acknowledge()
        self.gui.live.poll()
        self.assertTrue(self.gui.live.starting('bob'))
        self.assertFalse(self.gui.live.start('bob'))
        self.assertEqual(self.gui.submit.call_count, 1)
        self.assertEqual(self.gui.state.feedback.revision, before)
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture',
            'self',
            live_contexts=[
                LiveContextEntry(
                    'Bob', 'bob', True, 'connecting', outbound_attempt_id='a'
                )
            ],
        )
        self.gui.live.poll()
        self.assertTrue(self.gui.live.starting('bob'))
        self.assertEqual(self.gui.live.failure('bob'), '')

    def test_failure_before_ack_is_inline_and_survives_ack_until_explicit_retry(
        self,
    ) -> None:
        """Broadcast ordering cannot lose failure or create a duplicate global notice."""
        self.assertTrue(self.gui.live.start('bob'))
        before = self.gui.state.feedback.revision
        self.gui.live.install(Update(0, 'event', ConnectionFailedEvent('Bob', 'bob')))
        self.acknowledge()
        self.assertFalse(self.gui.live.starting('bob'))
        self.assertIn('could not connect', self.gui.live.failure('bob'))
        self.assertEqual(self.gui.state.feedback.revision, before)
        self.assertTrue(self.gui.live.start('bob'))
        self.assertEqual(self.gui.live.failure('bob'), '')
        self.assertTrue(self.gui.live.starting('bob'))
        self.assertEqual(self.gui.submit.call_count, 2)

    def test_departed_request_failure_notifies_once_and_scopes_the_contact(
        self,
    ) -> None:
        """The result remains understandable after navigating away from its peer."""
        self.assertTrue(self.gui.live.start('bob'))
        self.acknowledge()
        self.gui.state.route = Route('V17')
        failed = Update(0, 'event', ConnectionFailedEvent('Bob', 'bob'))
        self.gui.live.install(failed)
        revision = self.gui.state.feedback.revision
        self.assertIn('Bob: Live could not connect', self.gui.state.feedback.text)
        self.gui.live.install(failed)
        self.assertEqual(self.gui.state.feedback.revision, revision)

    def test_definite_failure_survives_a_later_missing_request_completion(self) -> None:
        """A timeout cannot turn already-confirmed rejection back into progress."""
        self.assertTrue(self.gui.live.start('bob'))
        mutation = self.gui.live.pending
        self.gui.live.install(Update(0, 'event', ConnectionRejectedEvent('Bob', 'bob')))
        self.gui.live.install(Update(0, mutation.operation))
        self.assertFalse(self.gui.live.starting('bob'))
        self.assertIn('declined', self.gui.live.failure('bob'))
        self.assertFalse(self.gui.live.retry_ready('bob'))
        self.gui.state.snapshot = RuntimeSnapshotEvent('fixture', 'self')
        self.gui.live.poll()
        self.assertTrue(self.gui.live.retry_ready('bob'))
        self.assertIn('declined', self.gui.live.failure('bob'))

    def test_explicit_close_discards_the_previous_connection_failure(self) -> None:
        """Reopening a deliberately closed local context cannot restore its old error."""
        self.assertTrue(self.gui.live.start('bob'))
        self.acknowledge()
        self.gui.live.install(Update(0, 'event', ConnectionFailedEvent('Bob', 'bob')))
        self.assertIn('could not connect', self.gui.live.failure('bob'))
        self.assertTrue(self.gui.live.close_context('bob'))
        self.assertEqual(self.gui.live.failure('bob'), '')
        self.assertFalse(self.gui.live.starting('bob'))

    def test_decline_is_distinct_from_local_cancel_and_mutual_connection_tiebreak(
        self,
    ) -> None:
        """Only a genuine remote rejection ends progress with an actionable failure."""
        self.assertTrue(self.gui.live.start('bob'))
        self.acknowledge()
        for event in (
            ConnectionRejectedEvent('Bob', 'bob', actor=ConnectionActor.LOCAL),
            ConnectionRejectedEvent(
                'Bob', 'bob', reason_code=ConnectionReasonCode.MUTUAL_TIEBREAKER_LOSER
            ),
        ):
            self.gui.live.install(Update(0, 'event', event))
            self.assertTrue(self.gui.live.starting('bob'))
        self.gui.live.install(Update(0, 'event', ConnectionRejectedEvent('Bob', 'bob')))
        self.assertIn('declined', self.gui.live.failure('bob'))

    def test_unknown_result_rechecks_before_explicit_retry(self) -> None:
        """Lost acknowledgment is reconciled without a second Connect command."""
        self.assertTrue(self.gui.live.start('bob'))
        mutation = self.gui.live.pending
        self.gui.live.install(Update(0, mutation.operation))
        self.assertFalse(self.gui.live.start('bob'))
        self.gui.live.poll()
        self.assertTrue(self.gui.live.starting('bob'))
        self.gui.state.snapshot = RuntimeSnapshotEvent('fixture', 'self')
        self.gui.live.poll()
        self.assertFalse(self.gui.live.starting('bob'))
        self.assertIn('could not be confirmed', self.gui.live.failure('bob'))
        self.assertEqual(self.gui.submit.call_count, 1)
        self.assertTrue(self.gui.live.start('bob'))

    def test_failure_retry_waits_for_authoritative_attempt_removal(self) -> None:
        """A failed broadcast cannot make a stale Cancel identity into a usable Retry."""
        self.assertTrue(self.gui.live.start('bob'))
        self.acknowledge()
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture',
            'self',
            live_contexts=[
                LiveContextEntry(
                    'Bob', 'bob', True, 'connecting', outbound_attempt_id='a'
                )
            ],
        )
        self.gui.live.install(Update(0, 'event', ConnectionFailedEvent('Bob', 'bob')))
        self.assertFalse(self.gui.live.retry_ready('bob'))
        self.gui.state.snapshot = RuntimeSnapshotEvent('fixture', 'self')
        self.gui.live.poll()
        self.assertTrue(self.gui.live.retry_ready('bob'))

    def test_racing_incoming_request_can_auto_accept_without_false_failure(
        self,
    ) -> None:
        """Core may fulfill explicit Connect by accepting an already-arrived invitation."""
        self.assertTrue(self.gui.live.start('bob'))
        mutation = self.gui.live.pending
        self.gui.live.install(
            Update(0, mutation.operation, ConnectionAutoAcceptedEvent('Bob', 'bob'))
        )
        self.assertTrue(self.gui.live.starting('bob'))
        self.assertEqual(self.gui.live.failure('bob'), '')
        self.assertEqual(self.gui.state.feedback.text, '')

    def test_connected_snapshot_and_event_clear_progress_without_feedback(self) -> None:
        """Connection success has one canonical status and does not reopen a modal."""
        for event_first in (False, True):
            with self.subTest(event_first=event_first):
                self.gui.state.snapshot = RuntimeSnapshotEvent('fixture', 'self')
                self.assertTrue(self.gui.live.start('bob'))
                self.acknowledge()
                before = self.gui.state.feedback.revision
                if event_first:
                    self.gui.live.install(
                        Update(0, 'event', ConnectedEvent('Bob', 'bob'))
                    )
                self.gui.state.snapshot = RuntimeSnapshotEvent(
                    'fixture',
                    'self',
                    live_contexts=[LiveContextEntry('Bob', 'bob', True, 'connected')],
                )
                self.gui.live.poll()
                self.assertFalse(self.gui.live.starting('bob'))
                self.assertEqual(self.gui.live.failure('bob'), '')
                self.assertEqual(self.gui.state.feedback.revision, before)

    def test_connected_event_keeps_start_guard_until_a_current_snapshot_arrives(
        self,
    ) -> None:
        """A broadcast preceding its snapshot cannot briefly reenable Start Live."""
        self.assertTrue(self.gui.live.start('bob'))
        self.acknowledge()
        self.gui.live.install(
            Update(0, 'event', ConnectedEvent('Bob', 'bob', revision=6))
        )
        self.gui.live.poll()
        self.assertTrue(self.gui.live.starting('bob'))
        self.assertFalse(self.gui.live.retry_ready('bob'))
        self.assertFalse(self.gui.live.start('bob'))
        self.gui.state.snapshot = RuntimeSnapshotEvent('fixture', 'self', revision=5)
        self.gui.live.poll()
        self.assertTrue(self.gui.live.starting('bob'))
        self.assertEqual(self.gui.live.failure('bob'), '')
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture',
            'self',
            live_contexts=[LiveContextEntry('Bob', 'bob', True, 'connected')],
            revision=6,
        )
        self.gui.live.poll()
        self.assertFalse(self.gui.live.starting('bob'))
        self.assertFalse(self.gui.live.retry_ready('bob'))
        self.assertEqual(self.gui.submit.call_count, 1)

    def test_stale_generation_revision_and_cover_do_not_publish_failure(self) -> None:
        """A former activation or older state cannot replace current request progress."""
        self.assertTrue(self.gui.live.start('bob'))
        self.acknowledge()
        for update in (
            Update(-1, 'event', ConnectionFailedEvent('Bob', 'bob')),
            Update(0, 'event', ConnectionFailedEvent('Bob', 'bob', revision=3)),
        ):
            self.gui.live.install(update)
            self.assertEqual(self.gui.live.failure('bob'), '')
        self.gui.state.covered = True
        self.gui.live.install(Update(0, 'event', ConnectionFailedEvent('Bob', 'bob')))
        self.assertEqual(self.gui.live.failure('bob'), '')
        self.assertEqual(self.gui.state.feedback.text, '')


class LiveCoreTests(unittest.TestCase):
    """Uses local encrypted storage and IPC, without any actual peer or device."""

    def setUp(self) -> None:
        """Creates an authorized GUI attached to an isolated Core.

        Args:
            None
        Returns:
            None
        """
        self.h = support.GuiProducerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
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
        self.gui.state.covered = False
        self.gui.state.route = Route('V07', delivery=Delivery.LIVE)
        self.observed = []
        install = self.gui.live.install

        def observe(update: Update) -> bool:
            """Records synthetic fixture results for integration failure diagnosis.

            Args:
                update: Synthetic fixture's current-generation result.
            Returns:
                bool: Real coordinator handling result.
            """
            if update.operation.startswith('live:'):
                self.observed.append(update.event)
            return install(update)

        self.gui.live.install = observe

    def queue(self, identity: str, direction: MessageDirection) -> None:
        """Creates a genuine retained Core item and its admitted GUI presentation.

        Args:
            identity: Stable fixture message ID.
            direction: Explicit inbound/outbound fixture identity.
        Returns:
            None
        """
        status = (
            MessageStatus.PENDING
            if direction is MessageDirection.OUT
            else MessageStatus.UNREAD
        )
        self.h.messages.queue_message(
            self.h.onion,
            direction,
            Delivery.LIVE,
            ContentType.TEXT,
            '{"text":"fixture"}',
            status,
            identity,
        )
        self.gui.transcript.admit(
            TranscriptItem(
                self.h.onion,
                Delivery.LIVE,
                MessageDirectionCode(direction.value),
                identity,
                'fixture',
                status=MessageStatusCode(status.value),
            )
        )
        self.gui.state.snapshot = self.h.client.runtime_snapshot()

    def settle(self) -> None:
        """Installs the explicit completion and scheduled current-state refresh.

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
                self.gui.live.pending is None
                and not self.gui.state.busy
                and not self.gui.receipts.busy
            ):
                break
        self.assertIsNone(self.gui.live.pending)
        self.assertFalse(self.gui.receipts.busy)

    def test_lost_fallback_reads_original_ids_without_repeating_conversion(
        self,
    ) -> None:
        """Actual converted receipts remove stale LIVE copies while unselected pending work stays.

        Args:
            None
        Returns:
            None
        """
        self.queue('selected', MessageDirection.OUT)
        self.queue('unselected', MessageDirection.OUT)
        self.queue('received', MessageDirection.IN)
        original = self.h.client.request
        mutations = []

        def lost(command: object, expected: object) -> object:
            """Hides only an actual successful fallback reply.

            Args:
                command: Current captured public operation.
                expected: Expected public response type.
            Returns:
                object: Actual metadata read or missing mutation result.
            """
            result = original(command, expected)
            if isinstance(command, FallbackCommand):
                mutations.append(command)
                return None
            return result

        with patch.object(self.h.client, 'request', side_effect=lost):
            self.assertTrue(self.gui.live.fallback(self.h.onion, ('selected',)))
            self.settle()
        self.assertEqual(len(mutations), 1)
        self.assertEqual(
            {item.msg_id for item in self.gui.transcript.items.values()},
            {'unselected', 'received'},
        )
        self.assertEqual(
            [item.msg_id for item in self.h.messages.get_chat_history(self.h.onion)],
            ['selected'],
        )

    def test_selective_fallback_is_atomic_and_preserves_message_identity(self) -> None:
        """Invalid selection converts nothing; successful conversion retains the same ID.

        Args:
            None
        Returns:
            None
        """
        self.queue('first', MessageDirection.OUT)
        self.queue('second', MessageDirection.OUT)
        self.assertTrue(self.gui.live.fallback(self.h.onion, ('first', 'missing')))
        self.settle()
        self.assertEqual(
            {
                record.msg_id
                for record in self.h.messages.get_pending_live_outbox(self.h.onion)
            },
            {'first', 'second'},
        )
        self.assertEqual(len(self.gui.transcript.items), 2)
        self.gui.state.route = Route('V09', self.h.onion, Delivery.LIVE)
        self.assertTrue(self.gui.live.fallback(self.h.onion, ('first',)))
        self.settle()
        self.assertEqual(
            self.gui.state.route, Route('V08', self.h.onion, Delivery.DROP)
        )
        self.assertEqual(self.gui.state.feedback.visible(), '', self.observed)
        self.assertEqual(
            [
                record.msg_id
                for record in self.h.messages.get_pending_live_outbox(self.h.onion)
            ],
            ['second'],
        )
        self.assertEqual(
            [item.msg_id for item in self.gui.transcript.items.values()], ['second']
        )
        self.assertEqual(self.gui.state.feedback.visible(), '')
        self.assertTrue(self.gui.live.fallback(self.h.onion))
        self.settle()
        self.assertEqual(self.h.messages.get_pending_live_outbox(self.h.onion), [])
        self.assertEqual(
            {item.msg_id for item in self.h.messages.get_chat_history(self.h.onion)},
            {'first', 'second'},
        )

    def test_bulk_footer_fallback_refreshes_drop_with_original_identities(self) -> None:
        """Only explicit conversion moves all pending own items into the DROP view."""
        self.queue('first', MessageDirection.OUT)
        self.queue('second', MessageDirection.OUT)
        self.queue('received', MessageDirection.IN)
        route = Route('V09', self.h.onion, Delivery.LIVE)
        self.gui.state.route = route
        self.assertEqual(pending_fallback_count(self.gui, route), 2)
        self.gui.refresh_state()
        self.settle()
        self.assertEqual(pending_fallback_count(self.gui, route), 2)
        self.assertEqual(self.h.messages.get_chat_history(self.h.onion), [])
        self.assertTrue(self.gui.live.fallback(self.h.onion))
        self.assertFalse(self.gui.live.fallback(self.h.onion))
        self.settle()
        self.gui.state.snapshot = self.h.client.runtime_snapshot()
        self.assertEqual(pending_fallback_count(self.gui, route), 0)
        self.assertEqual(
            self.gui.state.route, Route('V08', self.h.onion, Delivery.DROP)
        )
        self.assertEqual(
            {item.msg_id for item in self.h.messages.get_chat_history(self.h.onion)},
            {'first', 'second'},
        )
        self.assertEqual(
            [item.msg_id for item in self.gui.transcript.items.values()], ['received']
        )

    def test_live_root_uses_core_recency_then_stable_peer_ties(self) -> None:
        """Current Core transport or unresolved receipt activity orders equal-priority peers.

        Args:
            None
        Returns:
            None
        """
        peers = ['b' * 56, 'c' * 56, 'd' * 56]
        for peer, stamp in zip(peers, ('2020-01-01', '2020-01-02', '2020-01-02')):
            self.h.contacts.ensure_alias_for_onion(peer)
            self.h.messages.queue_message(
                peer,
                MessageDirection.OUT,
                Delivery.LIVE,
                ContentType.TEXT,
                '{"text":"fixture"}',
                MessageStatus.PENDING,
                peer[:1],
                timestamp=stamp + 'T00:00:00+00:00',
            )
        self.gui.state.snapshot = self.h.client.runtime_snapshot()
        self.assertEqual(
            [row.peer for row in conversation_rows(self.gui, Delivery.LIVE)],
            [peers[1], peers[2], peers[0]],
        )
        self.h.daemon._transport_state.touch_session_activity(peers[0], 1609459200.0)
        self.gui.state.snapshot = self.h.client.runtime_snapshot()
        self.assertEqual(
            [row.peer for row in conversation_rows(self.gui, Delivery.LIVE)],
            peers,
        )

    def test_close_rejects_pending_then_discards_only_live_after_resolution(
        self,
    ) -> None:
        """Close cannot delete unresolved outbound LIVE, DROP, or saved contact data.

        Args:
            None
        Returns:
            None
        """
        self.queue('outbound', MessageDirection.OUT)
        self.queue('inbound', MessageDirection.IN)
        self.assertFalse(self.gui.live.close_context(self.h.onion))
        self.assertEqual(len(self.gui.transcript.items), 2)
        self.assertTrue(self.gui.live.fallback(self.h.onion))
        self.settle()
        self.gui.state.snapshot = self.h.client.runtime_snapshot()
        self.assertTrue(self.gui.live.close_context(self.h.onion))
        self.settle()
        self.assertFalse(self.gui.transcript.items)
        self.assertEqual(self.h.messages.get_unread_live_count(self.h.onion), 0)
        self.assertEqual(
            [item.msg_id for item in self.h.messages.get_chat_history(self.h.onion)],
            ['outbound'],
        )


class LocalLiveTests(unittest.TestCase):
    """Checks volatile-only close and unknown-result handling without a transport."""

    def setUp(self) -> None:
        """Creates one locally retained consumed conversation.

        Args:
            None
        Returns:
            None
        """
        self.gui = GuiController(
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
        self.gui.state.covered = False
        self.gui.state.snapshot = RuntimeSnapshotEvent('fixture', 'self')
        self.gui.transcript.admit(
            TranscriptItem(
                'peer', Delivery.LIVE, MessageDirectionCode.IN, 'consumed', 'text'
            )
        )

    def test_local_close_releases_hidden_media_and_text_draft(self) -> None:
        """All local LIVE references disappear while unrelated DROP content remains.

        Args:
            None
        Returns:
            None
        """
        self.gui.state.set_draft('peer', Delivery.LIVE, 'unsent')
        self.gui.state.set_draft('peer', Delivery.DROP, 'keep')
        target = PlaybackTarget(
            0,
            'instance',
            'epoch',
            'peer',
            Delivery.LIVE,
            MessageDirectionCode.IN,
            'consumed',
        )
        self.gui.playback.cache.append(target, 0, b'01', complete=True)
        self.assertTrue(self.gui.live.close_context('peer'))
        self.assertFalse(self.gui.transcript.items)
        self.assertIsNone(self.gui.playback.cache.read(target, 0, 2))
        self.assertNotIn(('peer', Delivery.LIVE), self.gui.state.drafts)
        self.assertEqual(self.gui.state.drafts[('peer', Delivery.DROP)], 'keep')

    def test_unknown_fallback_preserves_source_and_never_repeats(self) -> None:
        """A lost result cannot fabricate conversion or create another send operation.

        Args:
            None
        Returns:
            None
        """
        self.gui.client = Mock()
        self.gui.submit = Mock(return_value=True)
        self.assertTrue(self.gui.live.fallback('peer', ('own',)))
        operation = self.gui.live.pending.operation
        self.gui.live.install(Update(0, operation))
        self.assertFalse(self.gui.live.fallback('peer', ('own',)))
        self.assertEqual(len(self.gui.transcript.items), 1)
        self.gui.state.snapshot = RuntimeSnapshotEvent('fixture', 'self')
        self.gui.live.poll()
        self.assertIsNone(self.gui.live.pending)
        self.assertEqual(self.gui.submit.call_count, 1)

    def test_end_waits_for_original_capture_and_keeps_its_context_identity(
        self,
    ) -> None:
        """A later snapshot cannot retarget an end requested during finalization.

        Args:
            None
        Returns:
            None
        """
        gui = self.gui
        gui.client = Mock()
        gui.submit = Mock(return_value=True)
        gui.state.capabilities = frozenset({'qualified_live_control'})
        binding = CaptureBinding(
            'instance', 'epoch', 0, 'peer', Delivery.LIVE, 'capture', 1
        )
        self.assertTrue(gui.voice.press.down(PressSource.POINTER, binding, True))
        gui.voice.press.accepted(binding)
        self.assertTrue(gui.live.end('peer', context_generation=1))
        self.assertFalse(gui.live.end('peer', context_generation=2))
        gui.live.poll()
        gui.submit.assert_not_called()
        self.assertTrue(gui.voice.press.complete(binding, confirmed=True))
        gui.live.poll()
        self.assertEqual(gui.submit.call_count, 1)
        gui.submit.call_args.args[1]()
        command = gui.client.request.call_args.args[0]
        self.assertEqual(command.context_generation, 1)
        self.assertIsNone(command.attempt_id)
        self.assertTrue(gui.voice.press.held)
