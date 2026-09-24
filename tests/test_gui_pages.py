"""Bounded archive and retained-page navigation through enclosing Core and GUI paths."""

import unittest
from unittest.mock import Mock

import test_gui_producers as support
from metor.client import FrontendProfileState
from metor.client import FrontendLaunchContext
from metor.core.api import (
    ContentType,
    Delivery,
    GetMessagesCommand,
    IpcCommand,
    MessageDirectionCode,
    MessagesDataEvent,
    RetainedMessagesEvent,
)
from metor.data.message import MessageDirection, MessageStatus
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update


class ArchivePageTests(unittest.TestCase):
    """Exercises persistent page boundaries without consuming unread state."""

    def setUp(self) -> None:
        """Starts one isolated encrypted fixture with no external peer communication."""
        self.h = support.GuiProducerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    def queue(
        self, identity: str, direction: MessageDirection = MessageDirection.IN
    ) -> None:
        """Creates an eligible DROP archive receipt using the storage service."""
        self.h.messages.queue_message(
            self.h.onion,
            direction,
            Delivery.DROP,
            ContentType.TEXT,
            'archive-' + identity,
            MessageStatus.UNREAD
            if direction is MessageDirection.IN
            else MessageStatus.PENDING,
            msg_id=identity,
        )

    def page(
        self,
        identity: str | None = None,
        direction: MessageDirectionCode | None = None,
        size: int = 4096,
    ) -> MessagesDataEvent:
        """Reads a two-row page through authenticated public IPC."""
        result = self.h.client.request(
            GetMessagesCommand(self.h.onion, 2, identity, direction, size),
            MessagesDataEvent,
        )
        self.assertIsInstance(result, MessagesDataEvent)
        return result

    def test_equal_timestamp_direction_boundaries_and_byte_limit(self) -> None:
        """Exact boundaries neither duplicate equal-time rows nor consume the inbox."""
        for identity in ('one', 'two', 'three'):
            self.queue(identity)
        self.queue('three', MessageDirection.OUT)
        first = self.page()
        self.assertEqual(
            [(row.msg_id, row.direction) for row in first.messages],
            [('three', MessageDirectionCode.IN), ('three', MessageDirectionCode.OUT)],
        )
        self.assertTrue(first.has_older)
        second = self.page('three', MessageDirectionCode.IN)
        self.assertEqual([row.msg_id for row in second.messages], ['one', 'two'])
        self.assertFalse(second.has_older)
        too_small = self.page(size=1)
        self.assertFalse(too_small.page_available)
        self.assertEqual(too_small.messages, [])
        self.assertEqual(self.h.messages.get_unread_counts()[self.h.onion], 3)
        absent = self.page('absent', MessageDirectionCode.IN)
        self.assertFalse(absent.page_available)
        legacy = self.h.client.request(
            GetMessagesCommand(self.h.onion, 2), MessagesDataEvent
        )
        self.assertEqual([row.msg_id for row in legacy.messages], ['three', 'three'])

    def test_gui_older_page_and_late_route_result(self) -> None:
        """The production controller installs older pages and rejects departed-route callbacks."""
        for identity in ('one', 'two', 'three'):
            self.queue(identity)
        gui = GuiController(
            FrontendLaunchContext(
                'voice-owned',
                Mock(
                    profile_state=lambda: FrontendProfileState(
                        'voice-owned', True, False, False
                    )
                ),
            )
        )
        self.addCleanup(gui.close)
        gui.client = self.h.client
        gui.state.snapshot = self.h.client.runtime_snapshot()
        gui.state.capabilities = frozenset(self.h.client.init_event.capabilities)
        gui.state.covered = False
        gui.state.route = Route('V08', self.h.onion, Delivery.DROP)
        gui.messages = self.page()
        self.assertTrue(gui.archive.older())
        gui.archive.poll()
        gui._worker.join(5)
        gui.poll()
        self.assertEqual([row.msg_id for row in gui.messages.messages], ['one'])
        old_operation = gui.archive._operation
        gui.navigate(Route('V12'))
        gui.mailbox.put(Update(gui.state.generation, old_operation, self.page()))
        gui.poll()
        self.assertIsNone(gui.messages)
        self.assertEqual(gui.state.route.view, 'V12')


class PageContractTests(unittest.TestCase):
    """Checks additive defaults and cursor ownership with no transport fixture."""

    def test_defaults_and_strict_opt_in(self) -> None:
        """Legacy writers retain semantics while partial/invalid page assertions fail."""
        old = IpcCommand.from_dict(
            {'command_type': 'get_messages', 'target': 'peer', 'limit': 2}
        )
        self.assertIsNone(old.before_msg_id)
        self.assertIsNone(old.max_payload_bytes)
        for kwargs in (
            {'before_msg_id': 'id'},
            {'max_payload_bytes': True},
            {'max_payload_bytes': 1024, 'limit': True},
        ):
            with self.assertRaises(ValueError):
                GetMessagesCommand('peer', **kwargs)

    def test_inventory_cursor_reset_and_stale_result(self) -> None:
        """A route replacement cannot adopt a previous cursor or metadata page."""
        gui = GuiController(
            FrontendLaunchContext(
                'fixture',
                Mock(
                    profile_state=lambda: FrontendProfileState(
                        'fixture', True, False, False
                    )
                ),
            )
        )
        gui.state.covered = False
        gui.state.route = Route('V09', 'peer', Delivery.LIVE)
        gui.inventory.page = RetainedMessagesEvent(next_cursor='exact-cursor')
        gui.inventory.more()
        self.assertEqual(gui.inventory.cursor, 'exact-cursor')
        gui.inventory._operation = 'inventory-page:1'
        gui.inventory.reset()
        self.assertTrue(
            gui.inventory.install(
                Update(
                    0, 'inventory-page:1', RetainedMessagesEvent(next_cursor='stale')
                )
            )
        )
        self.assertIsNone(gui.inventory.page)
        self.assertIsNone(gui.inventory.cursor)


if __name__ == '__main__':
    unittest.main()
