"""Immediate DROP navigation, bounded retained presentation, and truthful page loading."""

import threading
import unittest
from dataclasses import replace
from unittest.mock import Mock

from metor.client import FrontendLaunchContext
from metor.core.api import (
    Delivery,
    GetMessagesCommand,
    IpcCommand,
    IpcEvent,
    MessageDeletedEvent,
    MessageDirectionCode,
    MessageEntry,
    MessageOutcomeEvent,
    MessagesDataEvent,
    MessageStatusCode,
    RetainedMessagesEvent,
    RuntimeSnapshotEvent,
    RuntimeStateChangedEvent,
    TextContent,
)
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.runtime.drop import DropMutation
from metor.ui.gui.runtime.receipts import ReceiptTarget
from metor.ui.gui.runtime.transcript import TranscriptItem
from metor.ui.gui.state import Route
from metor.ui.gui.state.media import PlaybackTarget
from metor.ui.gui.state.mailbox import Update


class ArchiveLoadingTests(unittest.TestCase):
    """Exercise real admission with delayed SDK reads and route changes before completion."""

    def setUp(self) -> None:
        """Creates one authorized controller with inert typed public-service responses."""
        self.gui = GuiController(
            FrontendLaunchContext('fixture', Mock()), simulator=True
        )
        self.addCleanup(self.gui.close)
        self.gui.state.covered = False
        self.gui.state.route = Route('V08', 'peer', Delivery.DROP)
        self.gui.state.snapshot = RuntimeSnapshotEvent('fixture', 'local-peer')
        self.client = Mock()
        self.client.runtime_snapshot.return_value = self.gui.state.snapshot
        self.client.request.side_effect = self._request
        self.gui.client = self.client

    def _page(
        self, peer: str = 'peer', *, has_older: bool = False
    ) -> MessagesDataEvent:
        """Returns one previously authorized bounded page with canonical row identity."""
        return MessagesDataEvent(
            [
                MessageEntry(
                    MessageDirectionCode.IN,
                    MessageStatusCode.READ,
                    Delivery.DROP,
                    TextContent('Known Drop'),
                    '2026-10-07T10:00:00Z',
                    'known-drop',
                )
            ],
            'archive',
            peer,
            has_older=has_older,
        )

    def _request(self, command: IpcCommand, _expected: type[IpcEvent]) -> IpcEvent:
        """Provides finite typed read responses while leaving production admission intact."""
        if isinstance(command, GetMessagesCommand):
            return self._page(command.target)
        return RetainedMessagesEvent()

    def _hold_read(self) -> tuple[threading.Event, threading.Thread]:
        """Occupies the one read lane until the test explicitly permits completion."""
        started, release = threading.Event(), threading.Event()

        def work() -> None:
            """Waits outside the GUI thread without admitting extra operation workers."""
            started.set()
            if not release.wait(5):
                raise TimeoutError('Held read was not released')

        self.assertTrue(self.gui.submit('held-read', work, background=True))
        self.assertTrue(started.wait(5))
        worker = self.gui._worker
        assert worker is not None
        self.addCleanup(worker.join, 5)
        self.addCleanup(release.set)
        return release, worker

    def test_known_drop_is_present_before_same_peer_return_read_completes(self) -> None:
        """A slow unrelated query cannot blank known content or change either draft."""
        page = self._page()
        self.gui.messages = page
        self.gui.state.set_draft('peer', Delivery.DROP, 'Drop draft')
        self.gui.state.set_draft('peer', Delivery.LIVE, 'Live draft')
        self._hold_read()
        self.gui.navigate(Route('V09', 'peer', Delivery.LIVE))
        self.assertIs(self.gui.messages, page)
        self.gui.navigate(Route('V08', 'peer', Delivery.DROP))
        self.assertIs(self.gui.messages, page)
        self.assertTrue(self.gui.archive.loading)
        self.assertFalse(self.gui.state.busy)
        self.assertEqual(
            self.gui.state.drafts,
            {
                ('peer', Delivery.DROP): 'Drop draft',
                ('peer', Delivery.LIVE): 'Live draft',
            },
        )
        self.client.request.assert_not_called()

    def test_new_peer_never_inherits_content_and_loading_starts_before_admission(
        self,
    ) -> None:
        """The initial frame distinguishes pending history from an authoritative empty page."""
        self.gui.messages = self._page()
        self._hold_read()
        self.gui.navigate(Route('V08', 'other-peer', Delivery.DROP))
        self.assertIsNone(self.gui.messages)
        self.assertTrue(self.gui.archive.loading)
        self.assertEqual(self.gui.archive.error, '')
        self.assertFalse(self.gui.state.busy)

    def test_older_page_is_not_retained_as_latest_when_switching_delivery(self) -> None:
        """An older cursor cannot be relabeled as the newest DROP page after a LIVE visit."""
        self.gui.messages = self._page(has_older=True)
        self.gui.archive.before = MessageDirectionCode.IN, 'before-this'
        self._hold_read()
        self.gui.navigate(Route('V09', 'peer', Delivery.LIVE))
        self.gui.navigate(Route('V08', 'peer', Delivery.DROP))
        self.assertIsNone(self.gui.messages)
        self.assertIsNone(self.gui.archive.before)
        self.assertTrue(self.gui.archive.loading)

    def test_visible_initial_read_gets_next_turn_then_background_readers_continue(
        self,
    ) -> None:
        """Navigation takes one free read turn without an additional worker or lasting priority."""
        release, held = self._hold_read()
        self.gui.navigate(Route('V08', 'new-peer', Delivery.DROP))
        self.gui.refresh_state()
        release.set()
        held.join(5)
        self.gui.poll()
        worker = self.gui._worker
        assert worker is not None
        worker.join(5)
        self.assertIsInstance(
            self.client.request.call_args_list[0].args[0], GetMessagesCommand
        )
        self.client.runtime_snapshot.assert_not_called()
        self.gui.poll()
        self.assertIsNotNone(self.gui.messages)
        for _ in range(4):
            if self.gui._worker is not None:
                self.gui._worker.join(5)
            self.gui.poll()
        self.assertGreater(self.client.runtime_snapshot.call_count, 0)

    def test_older_navigation_can_replace_a_pending_background_refresh(self) -> None:
        """A refreshing latest page cannot swallow an explicit Older action."""
        page = self._page(has_older=True)
        self.gui.messages = page
        self.gui.archive._operation = 'archive:refresh:peer'
        self.assertTrue(self.gui.archive.loading)
        self.assertTrue(self.gui.archive.older())
        self.assertEqual(
            self.gui.archive.before, (MessageDirectionCode.IN, 'known-drop')
        )
        self.assertIs(self.gui.messages, page)
        self.gui.archive.install(
            Update(0, 'archive:refresh:peer', MessagesDataEvent([], 'Peer', 'peer'))
        )
        self.assertIs(self.gui.messages, page)
        self.assertTrue(self.gui.archive.loading)

    def test_failure_keeps_known_rows_and_retry_only_repeats_the_page_read(
        self,
    ) -> None:
        """Failure is inline, has no false empty state, and retry preserves the selected scope."""
        page = self._page()
        self.gui.messages = page
        self.client.request.return_value = None
        self.client.request.side_effect = None
        self.assertTrue(self.gui.archive.load())
        worker = self.gui._worker
        assert worker is not None
        worker.join(5)
        self.gui.poll()
        self.assertIs(self.gui.messages, page)
        self.assertFalse(self.gui.archive.loading)
        self.assertTrue(self.gui.archive.error)
        self.assertEqual(self.gui.state.status, '')
        self.client.request.side_effect = self._request
        self.assertTrue(self.gui.archive.retry())
        self.assertTrue(self.gui.archive.loading)
        self.assertEqual(self.gui.archive.error, '')
        assert self.gui._worker is not None
        self.gui._worker.join(5)
        self.gui.poll()
        self.assertFalse(self.gui.archive.loading)
        self.assertTrue(
            all(
                isinstance(call.args[0], GetMessagesCommand)
                for call in self.client.request.call_args_list
            )
        )

    def test_lock_revokes_page_and_old_read_before_authorized_return(self) -> None:
        """Neither a held callback nor navigation can restore private rows across a cover."""
        self.gui.messages = self._page()
        self.gui.archive._operation = 'archive:old:peer'
        generation = self.gui.state.generation
        self.assertTrue(self.gui.security.lock())
        self.assertIsNone(self.gui.messages)
        self.assertFalse(self.gui.archive.loading)
        self.gui.archive.install(Update(generation, 'archive:old:peer', self._page()))
        self.assertIsNone(self.gui.messages)
        self.gui.state.covered = False
        self.gui.state.route = Route('V08', 'peer', Delivery.DROP)
        self.assertTrue(self.gui.archive.loading)
        self.assertIsNone(self.gui.messages)

    def test_confirmed_delete_during_live_invalidates_retained_drop_page(self) -> None:
        """A confirmed local deletion cannot reappear from retained same-peer rows."""
        self.gui.messages = self._page()
        self.gui.navigate(Route('V09', 'peer', Delivery.LIVE))
        mutation = DropMutation('drop:1', 'peer', 'known-drop', MessageDirectionCode.IN)
        self.gui.drop.pending = mutation
        event = MessageDeletedEvent('Peer', 'known-drop', 'peer')
        self.assertTrue(self.gui.drop.install(Update(0, mutation.operation, event)))
        self.assertIsNone(self.gui.messages)

    def test_hidden_changed_archive_keeps_pending_and_unarchived_volatile_text(
        self,
    ) -> None:
        """External changes revoke only eligible known archive bodies, not unsent or LIVE content."""
        row = self._page().messages[0]
        pending = replace(
            row,
            direction=MessageDirectionCode.OUT,
            status=MessageStatusCode.PENDING,
            msg_id='pending',
        )
        self.gui.messages = replace(self._page(), messages=[row, pending])
        for identity, delivery, status in (
            ('known-drop', Delivery.DROP, MessageStatusCode.READ),
            ('volatile-only', Delivery.DROP, MessageStatusCode.READ),
            ('live-turn', Delivery.LIVE, MessageStatusCode.READ),
        ):
            self.gui.transcript.admit(
                TranscriptItem(
                    'peer',
                    delivery,
                    MessageDirectionCode.IN,
                    identity,
                    'content',
                    status=status,
                )
            )
        self.gui.navigate(Route('V09', 'peer', Delivery.LIVE))
        self.gui.archive.changed('peer')
        self.assertEqual(
            [entry.msg_id for entry in self.gui.messages.messages], ['pending']
        )
        self.assertEqual(
            {item.msg_id for item in self.gui.transcript.items.values()},
            {'volatile-only', 'live-turn'},
        )
        self._hold_read()
        self.gui.navigate(Route('V08', 'peer', Delivery.DROP))
        self.assertEqual(
            [entry.msg_id for entry in self.gui.messages.messages], ['pending']
        )
        self.assertTrue(self.gui.archive.loading)

    def test_advanced_receipt_outweighs_stale_pending_page_during_invalidation(
        self,
    ) -> None:
        """A stale pending row cannot preserve content after a positive delivered receipt."""
        row = replace(
            self._page().messages[0],
            direction=MessageDirectionCode.OUT,
            status=MessageStatusCode.PENDING,
        )
        self.gui.messages = replace(self._page(), messages=[row])
        self.gui.transcript.admit(
            TranscriptItem(
                'peer',
                Delivery.DROP,
                MessageDirectionCode.OUT,
                'known-drop',
                'content',
                status=MessageStatusCode.DELIVERED,
            )
        )
        self.gui.navigate(Route('V09', 'peer', Delivery.LIVE))
        self.gui.archive.changed('peer')
        self.assertIsNone(self.gui.messages)
        self.assertFalse(self.gui.transcript.items)

    def test_inbox_and_other_peer_changes_keep_the_same_peer_archive(self) -> None:
        """Ordinary LIVE inbox activity never revokes a known DROP page."""
        page = self._page()
        self.gui.messages = page
        self.gui.navigate(Route('V09', 'peer', Delivery.LIVE))
        self._hold_read()
        self.gui.mailbox.put(
            Update(0, 'event', RuntimeStateChangedEvent('inbox', 'peer'))
        )
        self.gui.mailbox.put(
            Update(0, 'event', RuntimeStateChangedEvent('messages', 'other-peer'))
        )
        self.gui.poll()
        self.assertIs(self.gui.messages, page)

    def test_generic_change_requires_exact_absence_before_revoking_media(self) -> None:
        """A harmless archive change cannot permanently disable later Voice retention."""
        self.gui.messages = self._page()
        target = PlaybackTarget(
            0,
            'profile',
            'epoch',
            'peer',
            Delivery.DROP,
            MessageDirectionCode.IN,
            'known-drop',
        )
        self.assertTrue(
            self.gui.playback.cache.append(target, 0, b'\x00\x01', complete=True)
        )
        self.gui.navigate(Route('V09', 'peer', Delivery.LIVE))
        occupied = ReceiptTarget(
            'other-peer', Delivery.DROP, MessageDirectionCode.IN, 'earlier-check'
        )
        self.gui.receipts.start((occupied,))
        self.gui.archive.changed('peer')
        self.gui.archive.poll()
        self.assertIn(
            ReceiptTarget('peer', Delivery.DROP, MessageDirectionCode.IN, 'known-drop'),
            self.gui.archive._checks,
        )
        self.assertIsNotNone(self.gui.playback.cache.read(target, 0, 2))
        self.gui.receipts.queue.clear()
        self.gui.archive.poll()
        self.assertFalse(self.gui.archive._checks)
        check = self.gui.receipts.queue.popleft()
        self.gui.receipts.current = check
        self.gui.receipts._operation = 'receipt:external'
        self.gui.receipts.install(
            Update(
                0,
                'receipt:external',
                MessageOutcomeEvent(
                    'peer',
                    'known-drop',
                    MessageDirectionCode.IN,
                    Delivery.DROP,
                    MessageStatusCode.READ,
                    True,
                ),
            )
        )
        self.assertIsNotNone(self.gui.playback.cache.read(target, 0, 2))
        self.gui.receipts.current = check
        self.gui.receipts._operation = 'receipt:deleted'
        self.gui.receipts.install(
            Update(
                0,
                'receipt:deleted',
                MessageOutcomeEvent(
                    'peer',
                    'known-drop',
                    MessageDirectionCode.IN,
                    Delivery.DROP,
                    MessageStatusCode.READ,
                    False,
                ),
            )
        )
        self.assertIsNone(self.gui.playback.cache.read(target, 0, 2))

    def test_changed_known_archive_rejects_prechange_page_and_confirms_visible_absence(
        self,
    ) -> None:
        """A captured old page cannot restore content after matching Core change evidence."""
        page = self._page()
        self.gui.messages = page
        self.gui.archive._operation = 'archive:before-delete'
        for identity in ('known-drop', 'volatile-only'):
            self.gui.transcript.admit(
                TranscriptItem(
                    'peer',
                    Delivery.DROP,
                    MessageDirectionCode.IN,
                    identity,
                    'content',
                    status=MessageStatusCode.READ,
                )
            )
        self.gui.archive.changed('peer')
        self.gui.messages = MessagesDataEvent([], 'Peer', 'peer')
        self.gui.archive.install(Update(0, 'archive:before-delete', page))
        self.assertFalse(self.gui.messages.messages)
        self.gui.archive.poll()
        target = self.gui.receipts.queue.popleft()
        self.gui.receipts.current = target
        self.gui.receipts._operation = 'receipt:deleted'
        self.gui.receipts.install(
            Update(
                0,
                'receipt:deleted',
                MessageOutcomeEvent(
                    'peer',
                    'known-drop',
                    MessageDirectionCode.IN,
                    Delivery.DROP,
                    MessageStatusCode.READ,
                    False,
                ),
            )
        )
        self.assertEqual(
            {item.msg_id for item in self.gui.transcript.items.values()},
            {'volatile-only'},
        )


if __name__ == '__main__':
    unittest.main()
