"""Bounded foreground text handoff using real Core IPC and protected presentation admission."""

import unittest
from unittest.mock import Mock

import test_gui_producers as support
from metor.client import FrontendLaunchContext
from metor.core.api import (
    ContentType,
    Delivery,
    IpcCommand,
    MarkReadCommand,
    MessageDirectionCode,
    UnreadMessagesEvent,
)
from metor.data.message import MessageDirection, MessageStatus
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.runtime.transcript import TranscriptItem
from metor.ui.gui.state import Route


class TextHandoffTests(unittest.TestCase):
    """Checks atomic limits, delivery separation and in-flight foreground payload retention."""

    def setUp(self) -> None:
        """Creates a temporary encrypted Core fixture without external peers or hardware."""
        self.h = support.GuiProducerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    def queue(self, identity: str, delivery: Delivery, payload: str) -> None:
        """Adds an isolated accepted inbound text through the existing message service."""
        self.h.messages.queue_message(
            contact_onion=self.h.onion,
            direction=MessageDirection.IN,
            delivery=delivery,
            content_type=ContentType.TEXT,
            payload=payload,
            status=MessageStatus.UNREAD,
            msg_id=identity,
        )

    def read(self, delivery: Delivery, count: int, size: int) -> UnreadMessagesEvent:
        """Uses the public typed operation and asserts its exact result type."""
        result = self.h.client.request(
            MarkReadCommand(self.h.onion, delivery, count, size), UnreadMessagesEvent
        )
        self.assertIsInstance(result, UnreadMessagesEvent)
        return result

    def test_atomic_bounds_preserve_excess_and_other_delivery(self) -> None:
        """A too-small budget consumes nothing; a one-row handoff leaves remaining text."""
        self.queue('drop-one', Delivery.DROP, 'first')
        self.queue('drop-two', Delivery.DROP, 'second')
        self.queue('live-one', Delivery.LIVE, 'live')
        self.assertEqual(self.read(Delivery.DROP, 1, 1).messages, [])
        first = self.read(Delivery.DROP, 1, 1024)
        self.assertEqual([item.msg_id for item in first.messages], ['drop-one'])
        second = self.read(Delivery.DROP, 1, 1024)
        self.assertEqual([item.msg_id for item in second.messages], ['drop-two'])
        live = self.read(Delivery.LIVE, 1, 1024)
        self.assertEqual([item.msg_id for item in live.messages], ['live-one'])

    def test_result_survives_route_departure_and_opaque_lock_cover(self) -> None:
        """A consumed original-peer batch is retained privately even after navigation/lock."""
        self.queue('foreground', Delivery.LIVE, 'protected foreground payload')
        gui = GuiController(FrontendLaunchContext('voice-owned', Mock()))
        self.addCleanup(gui.close)
        gui.client = self.h.client
        gui.state.snapshot = self.h.client.runtime_snapshot()
        gui.state.capabilities = frozenset(self.h.client.init_event.capabilities)
        gui.state.covered = False
        gui.state.route = Route('V09', self.h.onion, Delivery.LIVE)
        gui.handoff.needed = True
        gui.handoff.poll()
        self.assertGreater(gui.transcript.reserved_bytes, 0)
        free_items, free_bytes = gui.transcript.capacity()
        self.assertFalse(
            gui.transcript.admit(
                TranscriptItem(
                    'other',
                    Delivery.LIVE,
                    MessageDirectionCode.IN,
                    'overflow',
                    'x' * (free_bytes + 1),
                )
            )
        )
        self.assertGreaterEqual(free_items, 0)
        gui._worker.join(5)
        self.assertFalse(gui._worker.is_alive())
        gui.state.route = Route('V05')
        gui.state.covered = True
        gui.state.status = 'Locked'
        gui.poll()
        key = (self.h.onion, Delivery.LIVE, MessageDirectionCode.IN, 'foreground')
        self.assertEqual(gui.transcript.items[key].text, 'protected foreground payload')
        self.assertTrue(gui.state.covered)
        self.assertEqual(gui.state.status, 'Locked')
        self.assertEqual(gui.transcript.reserved_bytes, 0)
        self.assertEqual(self.read(Delivery.LIVE, 1, 1024).messages, [])

    def test_legacy_wire_defaults_and_strict_bounds(self) -> None:
        """Defaulted fields preserve old IPC writers while invalid bounds are rejected."""
        command = IpcCommand.from_dict(
            {'command_type': 'mark_read', 'target': 'peer', 'delivery': 'live'}
        )
        self.assertIsInstance(command, MarkReadCommand)
        self.assertIsNone(command.max_messages)
        self.assertIsNone(command.max_payload_bytes)
        for field in ('max_messages', 'max_payload_bytes'):
            with self.assertRaises(ValueError):
                MarkReadCommand('peer', **{field: True})


if __name__ == '__main__':
    unittest.main()
