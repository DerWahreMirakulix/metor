"""Notification privacy, source watermarks and finite presentation-only behavior."""

from dataclasses import asdict
import json
import unittest
from unittest.mock import Mock

from metor.client import FrontendLaunchContext
from metor.core.api import (
    ConnectionRetryEvent,
    ContactEntry,
    Delivery,
    DropConversationSummaryEntry,
    MessageReceivedEvent,
    RuntimeSnapshotEvent,
    TextContent,
    InboxNotificationEvent,
    ClientRestrictedEvent,
    ClientUnlockMethod,
    NotificationPrivacy,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.state.notifications import Notice, NoticeKind, NotificationStore


class NotificationStoreTests(unittest.TestCase):
    """Checks actual budget admission, watermark lifetime and current-fact replacement."""

    def test_clear_does_not_recreate_unchanged_state(self) -> None:
        store = NotificationStore()
        old = Notice(NoticeKind.DROP, 'peer', 'source-one', 2)
        store.reconcile([old])
        store.clear_center()
        store.reconcile([old])
        self.assertEqual(len(store.items), 0)
        store.reconcile([Notice(NoticeKind.DROP, 'peer', 'source-two', 3)])
        self.assertEqual(store.items[old.key].count, 3)
        store.dismiss({old.key})
        store.reconcile([])
        store.reconcile([old])
        self.assertIn(old.key, store.items)

    def test_full_store_prioritizes_calls_and_replaces_stale_facts(self) -> None:
        store = NotificationStore()
        store.reconcile(
            Notice(NoticeKind.DROP, str(index), 'current')
            for index in range(GuiLimits.NOTIFICATIONS)
        )
        self.assertFalse(
            store.put(Notice(NoticeKind.UNSTABLE, 'overflow', 'info', actionable=False))
        )
        call = Notice(NoticeKind.CALL, 'caller', 'request')
        self.assertTrue(store.put(call))
        self.assertEqual(len(store.items), GuiLimits.NOTIFICATIONS)
        self.assertLessEqual(store.bytes, GuiLimits.NOTIFICATION_BYTES)
        store.reconcile([Notice(NoticeKind.CALL, 'new-caller', 'new-request')])
        self.assertEqual(list(store.items), [(NoticeKind.CALL, 'new-caller')])
        self.assertFalse(store.put(Notice(NoticeKind.CALL, 'x' * 4096, 'oversized')))
        store.clear_center()
        self.assertLessEqual(store.bytes, GuiLimits.NOTIFICATION_BYTES)

    def test_seen_selection_and_abandon_are_volatile_only(self) -> None:
        store = NotificationStore()
        notice = Notice(NoticeKind.LIVE, 'peer', 'generation')
        store.put(notice)
        store.mark_seen()
        self.assertTrue(store.items[notice.key].seen)
        store.selecting = True
        store.selected.add(notice.key)
        store.dismiss(set(store.selected))
        self.assertFalse(store.selected)
        self.assertIn(notice.key, store.watermarks)
        store.abandon()
        self.assertFalse(
            store.items or store.watermarks or store.selected or store.selecting
        )


class NotificationProjectionTests(unittest.TestCase):
    """Exercises the production coordinator without any message-body notification path."""

    def setUp(self) -> None:
        self.gui = GuiController(FrontendLaunchContext('fixture', Mock()))
        self.gui.state.covered = False
        self.gui.state.route = Route('V06')
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture',
            '',
            epoch='epoch',
            contacts=[ContactEntry('Alice', 'peer')],
            conversations=[DropConversationSummaryEntry('Alice', 'peer', 2)],
        )
        self.gui.client = Mock()
        self.gui.command = Mock()

    def test_center_and_clear_never_consume_messages_or_rebuild_previews(self) -> None:
        self.gui.notifications.poll()
        store = self.gui.notifications.store
        self.assertEqual(len(store.items), 1)
        self.gui.notifications.observe(
            MessageReceivedEvent(
                'Alice',
                Delivery.LIVE,
                TextContent('SECRET BODY SENTINEL'),
                onion='peer',
                msg_id='private',
            )
        )
        encoded = json.dumps([asdict(item) for item in store.items.values()])
        self.assertNotIn('SECRET BODY SENTINEL', encoded)
        self.assertNotIn('Alice', encoded)
        self.gui.navigate(Route('V16'))
        store.mark_seen()
        store.clear_center()
        self.gui.notifications.poll()
        self.assertEqual(len(store.items), 0)
        self.assertEqual(self.gui.state.snapshot.conversations[0].unread_count, 2)
        self.gui.command.assert_not_called()
        self.gui.client.request.assert_not_called()

    def test_stale_navigation_is_removed_without_a_call(self) -> None:
        self.gui.notifications.poll()
        self.gui.state.snapshot.conversations.clear()
        self.gui.notifications.open((NoticeKind.DROP, 'peer'))
        self.assertEqual(self.gui.state.route.view, 'V06')
        self.assertEqual(self.gui.state.status, 'Item no longer available')
        self.gui.command.assert_not_called()

    def test_equal_count_new_arrival_replaces_dismissal_but_duplicate_does_not(
        self,
    ) -> None:
        """Exact arrival metadata distinguishes replacement without reading message bodies.

        Args:
            None
        Returns:
            None
        """
        from dataclasses import replace

        notifications = self.gui.notifications
        first = InboxNotificationEvent('Alice', 'peer', source_id='first')
        notifications.observe(first)
        notifications.poll()
        notifications.store.clear_center()
        notifications.observe(first)
        self.gui.state.snapshot = replace(self.gui.state.snapshot)
        notifications.poll()
        self.assertFalse(notifications.store.items)
        notifications.observe(
            InboxNotificationEvent('Alice', 'peer', source_id='second')
        )
        self.gui.state.snapshot = replace(self.gui.state.snapshot)
        notifications.poll()
        self.assertEqual(notifications.store.items[(NoticeKind.DROP, 'peer')].count, 2)

    def test_locked_activity_uses_only_permitted_events_and_no_historical_count(
        self,
    ) -> None:
        """Off cannot populate a hidden ledger; anonymous events retain only their kind.

        Args:
            None
        Returns:
            None
        """
        from dataclasses import replace

        notifications = self.gui.notifications
        self.gui.state.covered = True
        self.gui.security.restriction = ClientRestrictedEvent(ClientUnlockMethod.NONE)
        notifications.observe(InboxNotificationEvent('unknown', delivery=Delivery.LIVE))
        self.assertEqual(notifications.locked_activity, {Delivery.LIVE})
        notifications.open_locked()
        self.assertEqual(self.gui.state.route.view, 'V06')
        self.gui.command.assert_not_called()
        self.gui.state.covered = False
        notifications.poll()
        self.assertEqual(self.gui.state.route.view, 'V16')
        notifications.begin_lock()
        self.gui.state.covered = True
        self.gui.security._policy = replace(
            self.gui.security._policy, notifications_locked=NotificationPrivacy.OFF
        )
        notifications.observe(InboxNotificationEvent('Alice', 'peer', count=77))
        self.assertFalse(notifications.locked_activity)

    def test_covered_events_do_not_reconstruct_off_history_and_churn_coalesces(
        self,
    ) -> None:
        for revision in (1, 2, 2):
            self.gui.notifications.observe(
                ConnectionRetryEvent('Alice', 1, 3, onion='peer', revision=revision)
            )
        store = self.gui.notifications.store
        self.assertEqual(store.items[(NoticeKind.UNSTABLE, 'peer')].count, 2)
        self.gui.state.covered = True
        self.gui.notifications.observe(
            ConnectionRetryEvent('Alice', 2, 3, onion='other', revision=3)
        )
        self.assertNotIn((NoticeKind.UNSTABLE, 'other'), store.items)


if __name__ == '__main__':
    unittest.main()
