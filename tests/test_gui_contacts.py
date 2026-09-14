"""Contact intent and stale-alias safety through real encrypted Core IPC."""

import base64
import hashlib
import unittest
from unittest.mock import Mock, patch

import test_gui_producers as support
from metor.client import FrontendLaunchContext
from metor.core.api import (
    AliasNotFoundEvent,
    ContactEntry,
    Delivery,
    IpcEvent,
    RemoveContactCommand,
    RenameContactCommand,
    PeerNotFoundEvent,
    RuntimeSnapshotEvent,
    LiveContextEntry,
    ContactAddedEvent,
    AliasInUseEvent,
)
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update


def address(value: int) -> str:
    """Builds a valid public test identity from fixed nonsecret bytes."""
    public = bytes([value]) * 32
    checksum = hashlib.sha3_256(b'.onion checksum' + public + b'\x03').digest()[:2]
    return base64.b32encode(public + checksum + b'\x03').decode('ascii').lower()


class ContactCoreTests(unittest.TestCase):
    """Checks the public guard and an enclosing save/open flow against actual storage."""

    def setUp(self) -> None:
        """Starts a temporary encrypted profile without any external peer or camera."""
        self.h = support.GuiProducerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    def test_stale_alias_cannot_rename_or_remove_replacement_peer(self) -> None:
        """A second contact acquiring an old alias cannot become the original action target."""
        original, replacement = address(11), address(12)
        self.assertTrue(self.h.contacts.add_contact('alice', original).success)
        self.assertTrue(self.h.contacts.rename_contact('alice', 'anna').success)
        self.assertTrue(self.h.contacts.add_contact('alice', replacement).success)
        rename = self.h.client.request(
            RenameContactCommand('alice', 'wrong', original), IpcEvent
        )
        remove = self.h.client.request(
            RemoveContactCommand('alice', original), IpcEvent
        )
        self.assertIsInstance(rename, AliasNotFoundEvent)
        self.assertIsInstance(remove, PeerNotFoundEvent)
        self.assertEqual(self.h.contacts.get_onion_by_alias('alice'), replacement)
        self.assertEqual(self.h.contacts.get_onion_by_alias('anna'), original)
        self.assertIsNone(self.h.contacts.get_onion_by_alias('wrong'))

    def test_public_save_completes_original_drop_intent(self) -> None:
        """A real public save opens the correct DROP only after Core acknowledges it."""
        gui = GuiController(FrontendLaunchContext('voice-owned', Mock()))
        self.addCleanup(gui.close)
        gui.client = self.h.client
        gui.state.snapshot = self.h.client.runtime_snapshot()
        gui.state.capabilities = frozenset(self.h.client.init_event.capabilities)
        gui.state.covered = False
        gui.state.route = Route('V11', delivery=Delivery.DROP)
        gui.contacts.begin('drop')
        gui.contacts.form.raw = address(13) + '.onion'
        gui.contacts.form.alias = 'Saved Peer'
        self.assertTrue(gui.contacts.save())
        self.assertEqual(gui.state.route.view, 'V13')
        gui._worker.join(5)
        gui.poll()
        if gui._worker and gui._worker.is_alive():
            gui._worker.join(5)
        gui.poll()
        self.assertEqual(gui.state.route, Route('V08', address(13), Delivery.DROP))
        self.assertEqual(self.h.contacts.get_onion_by_alias('saved peer'), address(13))
        self.assertEqual(self.h.messages.get_chat_history(address(13)), [])

    def test_selected_remove_stops_on_lost_reply_and_reads_actual_saved_state(
        self,
    ) -> None:
        """A partial batch never silently sweeps unselected or later saved contacts.

        Args:
            None
        Returns:
            None
        """
        peers = [address(index) for index in (31, 32, 33)]
        for index, peer in enumerate(peers):
            self.assertTrue(
                self.h.contacts.add_contact('selected' + str(index), peer).success
            )
        gui = GuiController(FrontendLaunchContext('voice-owned', Mock()))
        self.addCleanup(gui.close)
        gui.client = self.h.client
        gui.state.snapshot = self.h.client.runtime_snapshot()
        gui.state.capabilities = frozenset(self.h.client.init_event.capabilities)
        gui.state.covered = False
        book = gui.contacts.book
        self.assertTrue(book.toggle(peers[0]))
        self.assertTrue(book.toggle(peers[1]))
        original = self.h.client.request
        commands = []

        def lost(command: object, expected: object) -> object:
            """Drops the first real removal reply; readback remains actual IPC.

            Args:
                command: Actual production request.
                expected: Requested public response type.
            Returns:
                object: Actual response, except one deliberately missing removal result.
            """
            result = original(command, expected)
            if isinstance(command, RemoveContactCommand):
                commands.append(command)
                return None
            return result

        with patch.object(self.h.client, 'request', side_effect=lost):
            self.assertTrue(book.remove(tuple(peers[:2])))
            self.assertFalse(book.remove(tuple(peers[:2])))
            for _ in range(12):
                if gui._worker is not None:
                    gui._worker.join(5)
                gui.poll()
                if not book.pending and not book.unknown and not gui.state.busy:
                    break
        self.assertEqual(len(commands), 1)
        self.assertFalse(book.pending or book.unknown)
        self.assertEqual(book.selected, {peers[1]})
        self.assertIsNone(self.h.contacts.get_onion_by_alias('selected0'))
        self.assertEqual(self.h.contacts.get_onion_by_alias('selected1'), peers[1])
        self.assertEqual(self.h.contacts.get_onion_by_alias('selected2'), peers[2])


class ContactIntentTests(unittest.TestCase):
    """Checks contact continuation and validation without a network implementation."""

    def setUp(self) -> None:
        """Creates typed current state and records only explicit command intentions."""
        self.gui = GuiController(FrontendLaunchContext('fixture', Mock()))
        self.gui.state.covered = False
        self.gui.state.route = Route('V12')
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture', address(1), contacts=[]
        )
        self.gui.command = Mock(return_value=True)

    def test_save_only_rejection_unknown_and_self_validation(self) -> None:
        """Failed, unknown or self contact input cannot become a call or lose its form."""
        self.gui.contacts.begin('save')
        form = self.gui.contacts.form
        form.raw, form.alias = address(1), 'self'
        self.assertFalse(self.gui.contacts.save())
        self.gui.command.assert_not_called()
        form.raw, form.alias = address(2), 'local'
        self.assertTrue(self.gui.contacts.save())
        self.gui.contacts.install(
            Update(0, 'contact:save:' + str(form.serial), AliasInUseEvent('local'))
        )
        self.assertEqual(self.gui.state.route.view, 'V13')
        self.assertEqual(form.alias, 'local')
        self.assertIsNone(self.gui.contacts._continuation)
        self.gui.contacts.install(Update(0, 'contact:save:' + str(form.serial)))
        self.assertTrue(form.unknown)
        self.assertFalse(self.gui.contacts.save())
        self.gui.contacts.install(
            Update(
                0,
                'contact:save:' + str(form.serial),
                ContactAddedEvent('local', 'fixture', address(2)),
            )
        )
        self.assertEqual(self.gui.state.route.view, 'V12')
        self.assertIsNone(self.gui.contacts._continuation)

    def test_existing_active_live_opens_without_another_ring(self) -> None:
        """An explicit Live picker selection opens its existing logical context."""
        peer = address(2)
        self.gui.state.snapshot.contacts = [ContactEntry('Peer', peer)]
        self.gui.state.snapshot.live_contexts = [
            LiveContextEntry('Peer', peer, True, 'connected')
        ]
        self.gui.contacts.select(peer, 'live')
        self.gui.contacts.poll()
        self.assertEqual(self.gui.state.route, Route('V09', peer, Delivery.LIVE))
        self.gui.command.assert_not_called()

    def test_failed_start_stays_in_picker(self) -> None:
        """An unavailable target never navigates or triggers an automatic retry."""
        peer = address(2)
        self.gui.state.route = Route('V11', delivery=Delivery.LIVE)
        self.gui.contacts.select(peer, 'live')
        self.gui.contacts.poll()
        self.assertEqual(self.gui.state.route.view, 'V11')
        self.gui.contacts.install(Update(0, 'contact:start:' + peer))
        self.gui.contacts.select(peer, 'live')
        self.gui.contacts.poll()
        self.assertEqual(self.gui.command.call_count, 1)
        self.assertEqual(self.gui.state.route.view, 'V11')


if __name__ == '__main__':
    unittest.main()
