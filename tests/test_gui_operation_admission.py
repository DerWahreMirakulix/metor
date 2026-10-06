"""Controller boundary regressions for independent work and confirmed UI projections."""

import threading
import unittest
from unittest.mock import Mock, patch

from metor.client import FrontendLaunchContext
from metor.core.api import (
    ContactAddedEvent,
    ContactEntry,
    ContactsDataEvent,
    Delivery,
    GetContactsListCommand,
    GetMessageOutcomeCommand,
    GetMessagesCommand,
    IpcEvent,
    MessageDirectionCode,
    MessageEntry,
    MessageOutcomeEvent,
    MessagesDataEvent,
    MessageStatusCode,
    RenameSuccessEvent,
    RuntimeSnapshotEvent,
    RuntimeStateChangedEvent,
    TextContent,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.runtime.contacts.flow import ContactForm
from metor.ui.gui.runtime.receipts import ReceiptTarget
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update


class GuiOperationAdmissionTests(unittest.TestCase):
    """Exercise real controller worker admission, mailbox ownership and contact projection."""

    def setUp(self) -> None:
        """Creates a covered-free SDK-free controller without a native event loop."""
        self.controller = GuiController(
            FrontendLaunchContext('fixture', Mock()), simulator=True
        )
        self.controller.state.covered = False
        self.controller.state.route = Route('V12')
        self.controller.state.snapshot = RuntimeSnapshotEvent(
            'fixture', 'local-peer', contacts=[ContactEntry('old', 'remote-peer')]
        )
        self.addCleanup(self.controller.close)

    def _read(
        self, operation: str, result: IpcEvent | None
    ) -> tuple[threading.Event, threading.Thread]:
        """Starts one deliberately blocked production-controller background worker.

        Args:
            operation: Exact query identity to preserve through the mailbox.
            result: Typed response returned after the explicit release.
        Returns:
            tuple: Release event and the bounded query worker.
        """
        release = threading.Event()
        started = threading.Event()

        def work() -> IpcEvent | None:
            """Waits for the fixture release while a foreground action can progress."""
            started.set()
            if not release.wait(5):
                raise TimeoutError('Blocked controller read was not released')
            return result

        self.assertTrue(self.controller.submit(operation, work, background=True))
        self.assertTrue(started.wait(5))
        worker = self.controller._worker
        assert worker is not None
        self.addCleanup(worker.join, 5)
        self.addCleanup(release.set)
        return release, worker

    def test_only_one_read_and_mutation_run_and_mutation_finishes_first(self) -> None:
        """A blocked read owns no UI busy state and cannot delay an explicit mutation."""
        gui = self.controller
        release, reader = self._read('snapshot', gui.state.snapshot)
        self.assertFalse(gui.state.busy)
        self.assertFalse(gui.submit('another-read', lambda: None, background=True))
        completed = threading.Event()

        def mutate() -> None:
            """Marks the mutation as started while the older read is still blocked."""
            completed.set()

        self.assertTrue(gui.submit('foreground', mutate))
        self.assertFalse(gui.submit('foreground', mutate))
        self.assertFalse(gui.submit('another-read', lambda: None, background=True))
        self.assertTrue(completed.wait(5))
        assert gui._worker is not None
        gui._worker.join(5)
        gui.poll()
        self.assertFalse(gui.state.busy)
        self.assertTrue(reader.is_alive())
        release.set()
        reader.join(5)
        gui.poll()
        self.assertTrue(gui.submit('new-read', lambda: None, background=True))
        gui._worker.join(5)

    def test_unrelated_worker_update_cannot_finish_foreground_owner(self) -> None:
        """A mailbox side-channel result cannot unlock controls for an unfinished action."""
        gui = self.controller
        release = threading.Event()
        self.addCleanup(release.set)
        self.assertTrue(gui.submit('foreground', lambda: release.wait(5) and None))
        gui.mailbox.put(Update(gui.state.generation, 'another-worker'))
        gui.poll()
        self.assertTrue(gui.state.busy)
        release.set()
        assert gui._worker is not None
        gui._worker.join(5)
        gui.poll()
        self.assertFalse(gui.state.busy)

    def test_snapshot_before_async_rename_cannot_restore_old_alias(self) -> None:
        """An unsolicited confirmed rename survives an older same-revision snapshot."""
        gui = self.controller
        release, reader = self._read('snapshot', gui.state.snapshot)
        gui.mailbox.put(
            Update(
                gui.state.generation,
                'event',
                RenameSuccessEvent('old', 'renamed', 'remote-peer'),
            )
        )
        gui.poll()
        self.assertEqual(gui.contacts.alias('remote-peer'), 'renamed')
        release.set()
        reader.join(5)
        gui.poll()
        self.assertEqual(gui.contacts.alias('remote-peer'), 'renamed')
        self.assertTrue(gui._refresh_needed)

    def test_snapshot_before_confirmed_contact_add_cannot_remove_contact(self) -> None:
        """A positive foreground acknowledgement is visible before a delayed read returns."""
        gui = self.controller
        release, reader = self._read('snapshot', gui.state.snapshot)
        self.assertTrue(
            gui.submit(
                'confirmed-contact',
                lambda: ContactAddedEvent('new', 'fixture', 'new-peer'),
            )
        )
        assert gui._worker is not None
        gui._worker.join(5)
        gui.poll()
        self.assertEqual(gui.contacts.alias('new-peer'), 'new')
        self.assertFalse(gui.state.busy)
        release.set()
        reader.join(5)
        gui.poll()
        self.assertEqual(gui.contacts.alias('new-peer'), 'new')

    def test_fence_preserves_exact_positive_outcome_read(self) -> None:
        """Read invalidation never throws away a positively confirmed exact cleanup receipt."""
        gui = self.controller
        target = ReceiptTarget(
            'remote-peer', Delivery.DROP, MessageDirectionCode.OUT, 'message'
        )
        gui.receipts.current = target
        gui.receipts._operation = 'receipt:1'
        result = MessageOutcomeEvent(
            'remote-peer',
            'message',
            MessageDirectionCode.OUT,
            Delivery.DROP,
            MessageStatusCode.DELIVERED,
            archive_available=False,
        )
        release, reader = self._read('receipt:1', result)
        self.assertTrue(gui.submit('foreground', lambda: None))
        assert gui._worker is not None
        gui._worker.join(5)
        gui.poll()
        release.set()
        reader.join(5)
        forgotten: list[tuple[object, ...]] = []
        gui.playback.forget = lambda *args: forgotten.append(args)
        gui.poll()
        self.assertIsNone(gui.receipts.current)
        self.assertEqual(
            forgotten,
            [('remote-peer', Delivery.DROP, 'message', MessageDirectionCode.OUT)],
        )

    def test_abandoned_completion_cannot_release_new_activation_owner(self) -> None:
        """Old activation work stays bounded and cannot clear the next action's busy flag."""
        gui = self.controller
        old_release = threading.Event()
        self.addCleanup(old_release.set)
        self.assertTrue(gui.submit('old', lambda: old_release.wait(5) and None))
        old_worker = gui._worker
        assert old_worker is not None
        gui.close()
        self.assertFalse(gui.submit('new', lambda: None))
        old_release.set()
        old_worker.join(5)
        new_release = threading.Event()
        self.addCleanup(new_release.set)
        self.assertTrue(gui.submit('new', lambda: new_release.wait(5) and None))
        gui.poll()
        self.assertTrue(gui.state.busy)
        new_release.set()
        assert gui._worker is not None
        gui._worker.join(5)
        gui.poll()
        self.assertFalse(gui.state.busy)

    def test_unknown_text_reconciliation_precedes_continuous_state_refreshes(
        self,
    ) -> None:
        """State events cannot prevent bounded same-ID readback or cause a second send."""
        gui = self.controller
        gui.command = Mock(return_value=True)
        gui.state.capabilities = frozenset({'message_outcome'})
        gui.state.set_draft('remote-peer', Delivery.DROP, 'one exact send')
        gui.send_text('remote-peer', Delivery.DROP)
        action = next(iter(gui.text.operations))
        identity = action.removeprefix('A11:')
        gui.text.install(Update(gui.state.generation, action))
        client = Mock()
        gui.client = client
        client.runtime_snapshot.return_value = gui.state.snapshot
        client.request.side_effect = [
            MessageOutcomeEvent('remote-peer', identity),
            MessageOutcomeEvent(
                'remote-peer',
                identity,
                status=MessageStatusCode.DELIVERED,
                delivery=Delivery.DROP,
            ),
        ]
        with patch(
            'metor.ui.gui.runtime.text.time.monotonic', return_value=100.0
        ) as clock:
            for index in range(6):
                if gui._worker is not None:
                    gui._worker.join(5)
                clock.return_value = 100.0 + index * GuiLimits.TEXT_OUTCOME_SECONDS
                gui.mailbox.put(
                    Update(
                        gui.state.generation,
                        'event',
                        RuntimeStateChangedEvent('messages', 'remote-peer'),
                    )
                )
                gui.poll()
        self.assertEqual(client.request.call_count, 2)
        for call in client.request.call_args_list:
            self.assertEqual(
                call.args[0], GetMessageOutcomeCommand('remote-peer', identity)
            )
        gui.command.assert_called_once()
        self.assertFalse(gui.text.pending('remote-peer', Delivery.DROP))
        self.assertNotIn(('remote-peer', Delivery.DROP), gui.state.drafts)
        if gui._worker is not None:
            gui._worker.join(5)

    def test_message_events_do_not_starve_or_invalidate_contact_save_readback(
        self,
    ) -> None:
        """A captured ContactsData reply confirms Save while unrelated messages keep arriving."""
        gui = self.controller
        form = ContactForm(
            1,
            'save',
            'remote-peer',
            alias='saved',
            unknown=True,
            submitted_alias='saved',
        )
        gui.contacts.form = form
        gui.contacts._check_needed = True
        gui.state.route = Route('V13')
        client = Mock()
        gui.client = client
        client.runtime_snapshot.return_value = gui.state.snapshot
        release, started = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def query(command: object, _expected: object) -> ContactsDataEvent:
            """Captures confirmed contacts and holds only their response delivery."""
            self.assertIsInstance(command, GetContactsListCommand)
            result = ContactsDataEvent(
                [ContactEntry('saved', 'remote-peer')], [], 'fixture'
            )
            started.set()
            if not release.wait(5):
                raise TimeoutError('Contact readback fixture was not released')
            return result

        client.request.side_effect = query
        gui._refresh_needed = True
        gui.poll()
        self.assertTrue(started.wait(5))
        reader = gui._worker
        assert reader is not None
        for _ in range(3):
            gui.mailbox.put(
                Update(
                    gui.state.generation,
                    'event',
                    RuntimeStateChangedEvent('messages', 'remote-peer'),
                )
            )
            gui.poll()
        self.assertTrue(form.unknown)
        release.set()
        reader.join(5)
        gui.poll()
        self.assertFalse(form.unknown)
        self.assertFalse(form.pending)
        self.assertEqual(gui.contacts.alias('remote-peer'), 'saved')
        client.request.assert_called_once()
        if gui._worker is not None:
            gui._worker.join(5)

    def test_contact_read_fence_still_rejects_reply_before_confirmed_rename(
        self,
    ) -> None:
        """Unrelated messages preserve contact reads; a real rename supersedes their alias facts."""
        gui = self.controller
        original = ContactsDataEvent(
            [ContactEntry('old', 'remote-peer')], [], 'fixture'
        )
        release, reader = self._read('contact:check:1', original)
        gui.mailbox.put(
            Update(
                gui.state.generation,
                'event',
                RenameSuccessEvent('old', 'renamed', 'remote-peer'),
            )
        )
        gui.poll()
        release.set()
        reader.join(5)
        gui.poll()
        self.assertEqual(gui.contacts.alias('remote-peer'), 'renamed')

    def test_generic_archive_gets_read_turn_despite_continuous_snapshot_requests(
        self,
    ) -> None:
        """Fair admission reads the archive and still polls lifecycle owners on every loop."""
        gui = self.controller
        gui.state.route = Route('V08', 'remote-peer', Delivery.DROP)
        client = Mock()
        gui.client = client
        client.runtime_snapshot.return_value = gui.state.snapshot
        gui.calls.poll = Mock(return_value=False)
        archive = MessagesDataEvent([], 'old', 'remote-peer')

        def query(command: object, _expected: object) -> MessagesDataEvent:
            """Records one genuine archive-query admission without any extra command families."""
            self.assertIsInstance(command, GetMessagesCommand)
            return archive

        client.request.side_effect = query
        for _ in range(6):
            if gui._worker is not None:
                gui._worker.join(5)
            gui.mailbox.put(
                Update(
                    gui.state.generation,
                    'event',
                    RuntimeStateChangedEvent('messages', 'remote-peer'),
                )
            )
            gui.poll()
        self.assertGreater(client.runtime_snapshot.call_count, 0)
        self.assertGreater(client.request.call_count, 0)
        self.assertIsNotNone(gui.messages)
        self.assertEqual(gui.calls.poll.call_count, 6)
        if gui._worker is not None:
            gui._worker.join(5)

    def test_held_archive_response_installs_after_continuous_message_events(
        self,
    ) -> None:
        """Messages arriving during query delivery request refresh without discarding its text."""
        gui = self.controller
        gui.state.route = Route('V08', 'remote-peer', Delivery.DROP)
        client = Mock()
        gui.client = client
        client.runtime_snapshot.return_value = gui.state.snapshot
        release, started = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        page = MessagesDataEvent(
            [
                MessageEntry(
                    MessageDirectionCode.OUT,
                    MessageStatusCode.DELIVERED,
                    Delivery.DROP,
                    TextContent('durable held response'),
                    'timestamp',
                    'held-text',
                )
            ],
            'old',
            'remote-peer',
        )

        def query(command: object, _expected: object) -> MessagesDataEvent:
            """Holds an archive-request response while asynchronous state events arrive."""
            self.assertIsInstance(command, GetMessagesCommand)
            started.set()
            if not release.wait(5):
                raise TimeoutError('Held archive query was not released')
            return page

        client.request.side_effect = query
        self.assertTrue(gui.archive.load())
        self.assertTrue(started.wait(5))
        reader = gui._worker
        assert reader is not None
        for _ in range(3):
            gui.mailbox.put(
                Update(
                    gui.state.generation,
                    'event',
                    RuntimeStateChangedEvent('messages', 'remote-peer'),
                )
            )
            gui.poll()
        release.set()
        reader.join(5)
        gui.poll()
        self.assertIsNotNone(gui.messages)
        self.assertEqual(
            gui.messages.messages[0].content, TextContent('durable held response')
        )
        self.assertEqual(gui.messages.messages[0].status, MessageStatusCode.DELIVERED)
        if gui._worker is not None:
            gui._worker.join(5)
