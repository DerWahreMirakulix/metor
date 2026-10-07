"""Contact intent and stale-alias safety through real encrypted Core IPC."""

import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import threading
import unittest
from unittest.mock import Mock, patch

import test_gui_producers as support
from metor.client import FrontendProfileState
from metor.client import FrontendLaunchContext
from metor.core.api import (
    AliasNotFoundEvent,
    ContactEntry,
    Delivery,
    IpcEvent,
    IpcCommand,
    RemoveContactCommand,
    RenameContactCommand,
    PeerNotFoundEvent,
    RuntimeSnapshotEvent,
    LiveContextEntry,
    ContactAddedEvent,
    AliasInUseEvent,
    AddContactCommand,
    AliasRenamedEvent,
    ContactsDataEvent,
    GetContactsListCommand,
    DropConversationSummaryEntry,
    PendingConnectionEntry,
    PendingConnectionReasonCode,
    ConnectionOrigin,
    RenameSuccessEvent,
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

    def test_public_display_case_and_unicode_alias_uniqueness(self) -> None:
        """Encrypted IPC preserves spelling while equivalent aliases cannot retarget a peer."""
        original, replacement = address(14), address(15)
        added = self.h.client.request(
            AddContactCommand('  Straße  ', original), IpcEvent
        )
        self.assertIsInstance(added, ContactAddedEvent)
        self.assertEqual(added.alias, 'Straße')
        duplicate = self.h.client.request(
            AddContactCommand('STRASSE', replacement), IpcEvent
        )
        self.assertIsInstance(duplicate, AliasInUseEvent)
        renamed = self.h.client.request(
            RenameContactCommand('strasse', 'STRAßE', original), IpcEvent
        )
        self.assertIsInstance(renamed, AliasRenamedEvent)
        self.assertEqual((renamed.old_alias, renamed.new_alias), ('Straße', 'STRAßE'))
        self.assertEqual(self.h.contacts.get_onion_by_alias('strasse'), original)
        contacts = self.h.client.request(GetContactsListCommand(), ContactsDataEvent)
        self.assertEqual(
            [(item.alias, item.onion) for item in contacts.saved],
            [('STRAßE', original)],
        )
        removed = self.h.client.request(
            RemoveContactCommand('STRASSE', original), IpcEvent
        )
        self.assertEqual(removed.alias, 'STRAßE')
        self.assertIsNone(self.h.contacts.get_alias_by_onion(original))

    def test_save_is_visible_on_return_before_any_snapshot_refresh(self) -> None:
        """Core's positive save result supplies the returned contact row on the same GUI poll."""
        peer = address(16)
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
        gui.state.covered = False
        gui.state.route = Route('V12')
        gui.refresh_state = Mock()
        gui.contacts.begin('save')
        form = gui.contacts.form
        form.raw, form.alias = peer, 'McAlice'
        self.assertTrue(gui.contacts.save())
        self.assertEqual(gui.contacts.book.rows(), [])
        gui._worker.join(5)
        gui.poll()
        self.assertEqual(gui.state.route.view, 'V12')
        self.assertEqual(
            [(item.onion, item.alias) for item in gui.contacts.book.rows()],
            [(peer, 'McAlice')],
        )
        self.assertEqual(gui.contacts.alias(peer), 'McAlice')

    def test_legacy_equivalent_aliases_do_not_resolve_an_arbitrary_peer(self) -> None:
        """Existing Unicode collisions remain exact-addressable and block new equivalent labels."""
        first, second, third = address(17), address(18), address(19)
        self.h.contacts._sql.peers.insert(first, 'straße', True)
        self.h.contacts._sql.peers.insert(second, 'strasse', True)
        self.assertEqual(self.h.contacts.get_onion_by_alias('straße'), first)
        self.assertEqual(self.h.contacts.get_onion_by_alias('strasse'), second)
        self.assertIsNone(self.h.contacts.get_onion_by_alias('STRASSE'))
        duplicate = self.h.client.request(AddContactCommand('STRASSE', third), IpcEvent)
        self.assertIsInstance(duplicate, AliasInUseEvent)
        stale = self.h.client.request(
            RenameContactCommand('STRASSE', 'Wrong', first), IpcEvent
        )
        self.assertIsInstance(stale, AliasNotFoundEvent)
        self.assertEqual(self.h.contacts.get_alias_by_onion(first), 'straße')

    def test_save_discovered_alias_preserves_requested_case(self) -> None:
        """Saving the peer under its existing label can promote it without a false collision."""
        peer = address(20)
        original = self.h.contacts.ensure_alias_for_onion(peer)
        self.assertTrue(self.h.contacts.rename_contact(original, 'McPeer').success)
        event = self.h.client.request(AddContactCommand('MCPEER', peer), IpcEvent)
        self.assertIsInstance(event, ContactAddedEvent)
        self.assertEqual(event.alias, 'MCPEER')
        self.assertEqual(self.h.contacts.get_alias_by_onion(peer), 'MCPEER')

    def test_parallel_authenticated_clients_keep_one_alias_owner(self) -> None:
        """Concurrent real IPC additions and renames share the same case-insensitive namespace."""
        peers = address(21), address(22)

        def pair(commands: tuple[IpcCommand, IpcCommand]) -> list[IpcEvent]:
            """Starts two actual independently authenticated requests at the same barrier."""
            start = threading.Barrier(2)

            def request(index: int) -> IpcEvent:
                """Preserves each SDK client's independent request and response correlation."""
                start.wait(5)
                client = self.h.client if index == 0 else self.h.other
                return client.request(commands[index], IpcEvent)

            with ThreadPoolExecutor(max_workers=2) as workers:
                futures = [workers.submit(request, index) for index in range(2)]
                return [future.result(5) for future in futures]

        added = pair(
            (
                AddContactCommand('Straße', peers[0]),
                AddContactCommand('STRASSE', peers[1]),
            )
        )
        self.assertEqual(
            sum(isinstance(event, ContactAddedEvent) for event in added), 1
        )
        self.assertEqual(sum(isinstance(event, AliasInUseEvent) for event in added), 1)
        owner = self.h.contacts.get_onion_by_alias('strasse')
        self.assertIn(owner, peers)
        labels = [
            item
            for item in self.h.contacts.get_contacts_data().saved
            if item.alias.casefold() == 'strasse'
        ]
        self.assertEqual([item.onion for item in labels], [owner])

        peers = address(23), address(24)
        self.assertIsInstance(
            self.h.client.request(AddContactCommand('First', peers[0]), IpcEvent),
            ContactAddedEvent,
        )
        self.assertIsInstance(
            self.h.other.request(AddContactCommand('Second', peers[1]), IpcEvent),
            ContactAddedEvent,
        )
        renamed = pair(
            (
                RenameContactCommand('First', 'Ümit', peers[0]),
                RenameContactCommand('Second', 'üMIT', peers[1]),
            )
        )
        self.assertEqual(
            sum(isinstance(event, AliasRenamedEvent) for event in renamed), 1
        )
        self.assertEqual(
            sum(isinstance(event, AliasInUseEvent) for event in renamed), 1
        )
        owner = self.h.contacts.get_onion_by_alias('ÜMIT')
        self.assertIn(owner, peers)
        labels = [
            item
            for item in self.h.contacts.get_contacts_data().saved
            if item.alias.casefold() == 'ümit'
        ]
        self.assertEqual([item.onion for item in labels], [owner])

    def test_public_save_completes_original_drop_intent(self) -> None:
        """A real public save opens the correct DROP only after Core acknowledges it."""
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
        self.gui = GuiController(
            FrontendLaunchContext(
                'fixture',
                Mock(
                    profile_state=lambda: FrontendProfileState(
                        'fixture', True, False, False
                    )
                ),
            )
        )
        self.gui.state.covered = False
        self.gui.state.route = Route('V12')
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture', address(1), contacts=[]
        )
        self.gui.command = Mock(return_value=True)

    def test_case_only_rename_updates_all_current_labels_after_confirmation(
        self,
    ) -> None:
        """Labels change together only after a successful result, preserving immutable identity."""
        peer = address(2)
        snapshot = self.gui.state.snapshot
        snapshot.contacts = [ContactEntry('alice', peer)]
        snapshot.conversations = [DropConversationSummaryEntry('alice', peer)]
        snapshot.live_contexts = [LiveContextEntry('alice', peer, True, 'connected')]
        snapshot.pending = [
            PendingConnectionEntry(
                'alice',
                peer,
                ConnectionOrigin.INCOMING,
                PendingConnectionReasonCode.USER_ACCEPT,
            )
        ]
        self.gui.state.capabilities = frozenset({'contact_identity_guard'})
        self.gui.contacts.begin('rename', peer)
        form = self.gui.contacts.form
        form.alias = 'Alice'
        self.assertTrue(self.gui.contacts.save())
        self.assertEqual(self.gui.contacts.alias(peer), 'alice')
        self.assertTrue(form.pending)
        self.assertFalse(self.gui.contacts.save())
        self.gui.contacts.install(
            Update(
                0,
                'contact:save:' + str(form.serial),
                AliasRenamedEvent('alice', 'Alice', peer),
            )
        )
        snapshot = self.gui.state.snapshot
        self.assertEqual(self.gui.state.route.view, 'V12')
        self.assertEqual(self.gui.contacts.alias(peer), 'Alice')
        self.assertEqual(
            [
                entry.alias
                for entry in snapshot.contacts
                + snapshot.conversations
                + snapshot.live_contexts
                + snapshot.pending
            ],
            ['Alice'] * 4,
        )

    def test_uncertain_save_readback_keeps_submitted_display_case(self) -> None:
        """Readback resolves the original request rather than lowercasing or replaying a save."""
        peer = address(2)
        self.gui.contacts.begin('save')
        form = self.gui.contacts.form
        form.raw, form.alias = peer, 'McAlice'
        self.assertTrue(self.gui.contacts.save())
        self.gui.contacts.install(Update(0, 'contact:save:' + str(form.serial)))
        self.assertTrue(form.unknown)
        self.assertEqual(self.gui.contacts.book.rows(), [])
        self.gui.contacts.install(
            Update(
                0,
                'contact:check:' + str(form.serial),
                ContactsDataEvent([ContactEntry('McAlice', peer)], [], 'fixture'),
            )
        )
        self.assertFalse(form.unknown)
        self.assertEqual(self.gui.state.route.view, 'V12')
        self.assertEqual(self.gui.contacts.alias(peer), 'McAlice')
        self.gui.command.assert_called_once()

    def test_old_contact_readback_cannot_replace_a_newer_confirmed_label(self) -> None:
        """A read started before another client's rename neither rolls back labels nor confirms a stale form."""
        peer = address(2)
        self.gui.contacts.begin('save')
        form = self.gui.contacts.form
        form.raw, form.alias = peer, 'McAlice'
        self.assertTrue(self.gui.contacts.save())
        self.gui.contacts.install(Update(0, 'contact:save:' + str(form.serial)))
        self.gui.state.snapshot.contacts = [ContactEntry('McAlice', peer)]
        form.pending = True
        self.gui.mailbox.put(
            Update(0, 'event', RenameSuccessEvent('McAlice', 'Updated', peer))
        )
        self.gui.mailbox.put(
            Update(
                0,
                'contact:check:' + str(form.serial),
                ContactsDataEvent([ContactEntry('McAlice', peer)], [], 'fixture'),
                background=True,
                read_epoch=0,
            )
        )
        self.gui.poll()
        self.assertEqual(self.gui.contacts.alias(peer), 'Updated')
        self.assertEqual(self.gui.state.route.view, 'V13')
        self.assertTrue(form.unknown)
        self.assertFalse(form.pending)
        self.assertTrue(self.gui.contacts._check_needed)
        self.gui.command.assert_called_once()

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

    def test_start_opens_progress_immediately_and_unknown_result_never_retries(
        self,
    ) -> None:
        """The picker uses the shared start lifecycle before any Core reply arrives."""
        peer = address(2)
        self.gui.state.route = Route('V11', delivery=Delivery.LIVE)
        self.gui.client = Mock()
        self.gui.submit = Mock(return_value=True)
        self.gui.contacts.select(peer, 'live')
        self.assertEqual(self.gui.state.route, Route('V09', peer, Delivery.LIVE))
        self.assertTrue(self.gui.live.starting(peer))
        mutation = self.gui.live.pending
        self.gui.live.install(Update(0, mutation.operation))
        self.gui.contacts.select(peer, 'live')
        self.gui.contacts.poll()
        self.assertEqual(self.gui.submit.call_count, 1)
        self.assertEqual(self.gui.state.route, Route('V09', peer, Delivery.LIVE))
        self.gui.back()
        self.assertEqual(self.gui.state.route.view, 'V11')

    def test_scanner_manual_fallback_keeps_intent_and_returns_to_caller(self) -> None:
        """The camera fallback adds no intermediate Back loop or implicit communication.

        Args:
            None
        Returns:
            None
        """
        for intent, route in (
            ('save', Route('V12')),
            ('drop', Route('V11', delivery=Delivery.DROP)),
            ('live', Route('V11', delivery=Delivery.LIVE)),
        ):
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
            self.addCleanup(gui.close)
            gui.state.covered = False
            gui.state.route = route
            gui.contacts.begin(intent, scan=True)
            self.assertEqual(gui.state.route.view, 'V14')
            gui.contacts.manual()
            self.assertEqual(gui.state.route.view, 'V13')
            self.assertEqual(gui.contacts.form.intent, intent)
            gui.back()
            self.assertEqual(gui.state.route, route)
            self.assertIsNone(gui.client)


if __name__ == '__main__':
    unittest.main()
