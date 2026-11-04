"""Guarded Call replacement through real presentation operations and protected SDK IPC."""

import base64
from collections.abc import Callable
from dataclasses import replace
import hashlib
import unittest
from unittest.mock import Mock, patch

import test_call_integration as support
from metor.client import FrontendLaunchContext
from metor.core.api import (
    CallInfo,
    CallReason,
    CallRejectedEvent,
    CallState,
    CallStateEvent,
    CallsStateEvent,
    ContactEntry,
    IpcEvent,
    RuntimeSnapshotEvent,
)
from metor.ui.gui.platform.audio import HeadsetAudio
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update


def _onion(value: int) -> str:
    """Builds a valid synthetic identity; this fixture never uses its private key."""
    public, version = bytes([value]) * 32, b'\x03'
    checksum = hashlib.sha3_256(b'.onion checksum' + public + version).digest()[:2]
    return base64.b32encode(public + checksum + version).decode('ascii').lower()


class CallHandoverTests(unittest.TestCase):
    """Explicit replacement cannot reuse an uncertain, stale or revoked old-call outcome."""

    def setUp(self) -> None:
        """Creates actual CallActions with captured SDK work and authoritative peer identities."""
        self.gui = GuiController(
            FrontendLaunchContext('fixture', Mock()), simulator=True
        )
        self.gui.simulator = False
        self.gui.state.covered = False
        self.gui.state.capabilities = frozenset({'calls'})
        self.source, self.target = _onion(1), _onion(2)
        self.gui.state.route = Route('V08', self.source)
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture',
            _onion(3),
            contacts=[
                ContactEntry('Source', self.source),
                ContactEntry('Target', self.target),
            ],
            profile_instance_id='instance',
            epoch='epoch',
            revision=10,
        )
        self.gui.client = Mock()
        self.gui.voice.configure(HeadsetAudio(1, 2), headset_confirmed=True)
        self.gui.voice.routes.input = 1
        self.gui.voice.routes.output = 2
        self.operations: list[tuple[str, Callable[[], IpcEvent | None]]] = []

        def submit(
            operation: str,
            work: Callable[[], IpcEvent | None],
            *,
            background: bool = False,
        ) -> bool:
            """Retains work without fabricating its Call result or opening native media."""
            self.operations.append((operation, work))
            return True

        self.gui.submit = submit
        self.calls = self.gui.calls
        self.old = CallInfo('old', self.source, 'Source', CallState.ACTIVE, owned=True)
        self.ended = replace(self.old, state=CallState.ENDED, reason=CallReason.HUNG_UP)
        self.calls.observe(CallStateEvent(self.old, epoch='epoch', revision=10))

    def begin(self) -> str:
        """Admits the immutable handover and executes its one existing SDK end operation."""
        self.assertTrue(self.calls.handover('old', self.target))
        operation, work = self.operations[-1]
        work()
        self.gui.client.hangup_call.assert_called_once_with('old')
        self.gui.client.start_call.assert_not_called()
        return operation

    def confirm_end(self) -> str:
        """Installs the exact positive reply and captures the subsequently admitted read."""
        operation = self.begin()
        self.calls.install(
            Update(0, operation, CallStateEvent(self.ended, epoch='epoch', revision=11))
        )
        self.calls.poll()
        read_operation, read = self.operations[-1]
        self.assertTrue(read_operation.startswith('call-handover:read:'))
        read()
        self.gui.client.get_calls.assert_called_once_with()
        return read_operation

    def proof(
        self, operation: str, *, revision: int = 12, calls: list[CallInfo] | None = None
    ) -> Update:
        """Returns a stamped proof for only the newly captured snapshot operation."""
        return Update(
            0,
            operation,
            CallsStateEvent(
                [self.ended] if calls is None else calls,
                epoch='epoch',
                revision=revision,
            ),
        )

    def starts(self) -> list[tuple[str, Callable[[], IpcEvent | None]]]:
        """Counts real request admissions rather than a mocked facade invocation."""
        return [item for item in self.operations if item[0].startswith('call:start:')]

    def test_positive_exact_end_and_fresh_read_start_target_once_after_media_cleanup(
        self,
    ) -> None:
        """A stopped old worker must finish before the proof is requested or target starts."""
        worker = Mock(done=Mock(is_set=Mock(return_value=False)))
        self.calls.worker = worker
        operation = self.begin()
        self.assertFalse(self.calls.handover('old', self.target))
        self.calls.install(
            Update(0, operation, CallStateEvent(self.ended, epoch='epoch', revision=11))
        )
        self.calls.poll()
        self.assertEqual(len(self.operations), 1)
        worker.done.is_set.return_value = True
        self.calls.poll()
        read_operation, read = self.operations[-1]
        read()
        self.calls.install(self.proof(read_operation))
        before = self.gui.state.route
        self.calls.poll()
        self.assertEqual(len(self.starts()), 1)
        start_operation, start = self.starts()[0]
        start()
        self.gui.client.start_call.assert_called_once()
        self.assertEqual(self.gui.client.start_call.call_args.args[0], self.target)
        identity = self.gui.client.start_call.call_args.args[1]
        self.calls.install(
            Update(
                0,
                start_operation,
                CallStateEvent(
                    CallInfo(
                        identity, self.target, 'Target', CallState.OUTGOING, owned=True
                    ),
                    epoch='epoch',
                    revision=13,
                ),
            )
        )
        self.calls.install(self.proof(read_operation))
        self.calls.poll()
        self.assertEqual(len(self.starts()), 1)
        self.assertEqual(self.gui.state.route, before)
        self.gui.client.cancel_call.assert_not_called()

    def test_invalid_or_removed_target_and_unowned_call_cannot_end_current_call(
        self,
    ) -> None:
        """Aliases, malformed onions and a stale confirmation target are rejected before hangup."""
        for target in (
            'Target',
            self.target + '.onion',
            self.target.upper(),
            _onion(4),
            'b' * 56,
        ):
            with self.subTest(target=target):
                self.assertFalse(self.calls.handover('old', target))
        self.gui.state.snapshot.contacts = [ContactEntry('Source', self.source)]
        self.assertFalse(self.calls.handover('old', self.target))
        self.gui.state.snapshot.contacts.append(ContactEntry('Target', self.target))
        self.calls.current = replace(self.old, owned=False)
        self.assertFalse(self.calls.handover('old', self.target))
        self.calls.current = self.old
        self.assertFalse(self.calls.handover('replacement', self.target))
        self.assertFalse(self.calls.handover('old', self.source))
        self.assertEqual(self.operations, [])

    def test_outgoing_handover_uses_cancel_once(self) -> None:
        """An unaccepted Call uses the existing cancel command instead of hangup."""
        self.calls.current = replace(self.old, state=CallState.OUTGOING)
        self.assertTrue(self.calls.handover('old', self.target))
        self.operations[-1][1]()
        self.gui.client.cancel_call.assert_called_once_with('old')
        self.gui.client.hangup_call.assert_not_called()
        self.assertEqual(self.starts(), [])

    def test_end_worker_captures_exact_identity_and_original_active_state(self) -> None:
        """Later presentation mutation cannot retarget the already admitted end command."""
        self.assertTrue(self.calls.handover('old', self.target))
        self.old.call_id = 'replacement'
        self.old.state = CallState.OUTGOING
        self.operations[-1][1]()
        self.gui.client.hangup_call.assert_called_once_with('old')
        self.gui.client.cancel_call.assert_not_called()

    def test_unqualified_activation_cannot_admit_handover(self) -> None:
        """Missing profile, epoch or revision provenance cannot qualify destructive consent."""
        for field in ('profile_instance_id', 'epoch', 'revision'):
            with self.subTest(field=field):
                self.setUp()
                setattr(self.gui.state.snapshot, field, None)
                self.assertFalse(self.calls.handover('old', self.target))
                self.assertEqual(self.operations, [])

    def test_wrong_operation_and_generation_do_not_consume_owned_end_result(
        self,
    ) -> None:
        """Unrelated completion cannot clear the pending operation or arm a continuation."""
        operation = self.begin()
        positive = CallStateEvent(self.ended, epoch='epoch', revision=11)
        self.calls.install(Update(0, 'call:end:other', positive))
        self.calls.install(Update(-1, operation, positive))
        self.assertEqual(self.calls._operation, (operation, 'old'))
        self.calls.poll()
        self.assertEqual(self.starts(), [])
        self.calls.install(Update(0, operation, positive))
        self.calls.poll()
        self.assertTrue(self.operations[-1][0].startswith('call-handover:read:'))

    def test_unknown_rejected_or_mismatched_end_never_continues(self) -> None:
        """Only an exact positive ended reply can begin the fresh proof phase."""
        outcomes = (
            None,
            CallRejectedEvent('old', CallReason.NOT_OWNER, epoch='epoch', revision=11),
            CallStateEvent(
                replace(self.ended, call_id='other'), epoch='epoch', revision=11
            ),
            CallStateEvent(
                replace(self.ended, peer=self.target), epoch='epoch', revision=11
            ),
            CallStateEvent(
                replace(self.ended, owned=False), epoch='epoch', revision=11
            ),
            CallStateEvent(self.old, epoch='epoch', revision=11),
            CallStateEvent(self.ended, epoch='other', revision=11),
            CallStateEvent(self.ended, epoch='epoch', revision=9),
            CallStateEvent(self.ended),
        )
        for outcome in outcomes:
            with self.subTest(outcome=type(outcome).__name__):
                self.setUp()
                operation = self.begin()
                self.calls.install(Update(0, operation, outcome))
                self.calls.install(self.proof('call-snapshot'))
                self.calls.poll()
                self.assertIsNone(self.calls._handover.pending)
                self.assertFalse(
                    any(
                        item[0].startswith('call-handover:read:')
                        for item in self.operations
                    )
                )
                self.assertEqual(self.starts(), [])

    def test_general_snapshot_or_other_read_cannot_supply_handover_proof(self) -> None:
        """A prior or unrelated snapshot does not replace the post-hangup exact read."""
        read_operation = self.confirm_end()
        self.calls.install(self.proof('call-snapshot'))
        self.calls.install(self.proof('call-handover:read:other'))
        self.calls.poll()
        self.assertEqual(self.starts(), [])
        self.calls.install(self.proof(read_operation))
        self.calls.poll()
        self.assertEqual(len(self.starts()), 1)

    def test_unknown_end_keeps_still_active_call_reachable_without_starting_target(
        self,
    ) -> None:
        """A post-timeout owned ACTIVE snapshot retains controls rather than losing the Call."""
        operation = self.begin()
        self.calls.install(Update(0, operation))
        self.calls.install(self.proof('call-snapshot', calls=[self.old]))
        self.assertIsNotNone(self.calls.current)
        self.assertEqual(self.calls.current.call_id, 'old')
        self.assertTrue(self.calls.show('old'))
        self.assertEqual(self.starts(), [])

    def test_stale_unknown_or_replacement_snapshot_cancels_continuation(self) -> None:
        """Fresh proof must still include the original owned ended Call and no ongoing replacement."""
        proofs = (
            (11, [self.ended]),
            (12, []),
            (12, [replace(self.ended, owned=False)]),
            (12, [replace(self.ended, peer=self.target)]),
            (12, [self.old]),
            (
                12,
                [
                    self.ended,
                    CallInfo('replacement', self.target, 'Target', CallState.ACTIVE),
                ],
            ),
        )
        for revision, calls in proofs:
            with self.subTest(revision=revision, calls=len(calls)):
                self.setUp()
                operation = self.confirm_end()
                self.calls.install(
                    self.proof(operation, revision=revision, calls=calls)
                )
                self.calls.poll()
                self.assertIsNone(self.calls._handover.pending)
                self.assertEqual(self.starts(), [])
        for outcome in (
            None,
            CallsStateEvent([self.ended], epoch='other', revision=12),
        ):
            with self.subTest(outcome=type(outcome).__name__):
                self.setUp()
                operation = self.confirm_end()
                self.calls.install(Update(0, operation, outcome))
                self.calls.poll()
                self.assertIsNone(self.calls._handover.pending)
                self.assertEqual(self.starts(), [])

    def test_newer_gui_mutation_invalidates_read_proof(self) -> None:
        """A concurrently superseded read cannot authorize an automatic Call start."""
        operation = self.confirm_end()
        self.gui._operations.invalidate_reads()
        self.calls.install(replace(self.proof(operation), read_epoch=0))
        self.calls.poll()
        self.assertIsNone(self.calls._handover.pending)
        self.assertEqual(self.starts(), [])

    def test_cover_profile_client_or_generation_change_cancels_before_start(
        self,
    ) -> None:
        """Changing activation or privacy never restores a previously consented continuation."""
        for change in ('cover', 'generation', 'instance', 'epoch', 'client'):
            with self.subTest(change=change):
                self.setUp()
                operation = self.confirm_end()
                self.calls.install(self.proof(operation))
                if change == 'cover':
                    self.gui.state.covered = True
                    self.calls.cover()
                    self.gui.state.covered = False
                elif change == 'generation':
                    self.gui.state.generation += 1
                elif change == 'instance':
                    self.gui.state.snapshot.profile_instance_id = 'replacement'
                elif change == 'epoch':
                    self.gui.state.snapshot.epoch = 'replacement'
                else:
                    self.gui.client = Mock()
                self.calls.poll()
                self.assertIsNone(self.calls._handover.pending)
                self.assertEqual(self.starts(), [])
                if change == 'cover':
                    self.assertEqual(self.calls.status, '')

    def test_changed_current_call_or_removed_target_cancels_ready_continuation(
        self,
    ) -> None:
        """The final start revalidates both current-call and selected-peer identity."""
        for change in ('current', 'target', 'audio'):
            with self.subTest(change=change):
                self.setUp()
                operation = self.confirm_end()
                self.calls.install(self.proof(operation))
                if change == 'current':
                    self.calls.current = CallInfo(
                        'replacement', self.target, 'Target', CallState.INCOMING
                    )
                elif change == 'target':
                    self.gui.state.snapshot.contacts.clear()
                else:
                    self.gui.voice.routes.input = None
                self.calls.poll()
                self.assertIsNone(self.calls._handover.pending)
                self.assertEqual(self.starts(), [])

    def test_new_current_call_event_revokes_continuation(self) -> None:
        """A new Call broadcast takes precedence over the older handover choice."""
        operation = self.confirm_end()
        self.calls.observe(
            CallStateEvent(
                CallInfo('replacement', self.target, 'Target', CallState.INCOMING),
                epoch='epoch',
                revision=12,
            )
        )
        self.calls.install(self.proof(operation))
        self.calls.poll()
        self.assertIsNone(self.calls._handover.pending)
        self.assertEqual(self.starts(), [])

    def test_deadline_cancels_while_end_or_read_has_unknown_lifetime(self) -> None:
        """An unanswered operation cannot retain an automatic future-start intention indefinitely."""
        self.begin()
        deadline = self.calls._handover.pending.deadline
        with patch(
            'metor.ui.gui.runtime.calls.handover.time.monotonic', return_value=deadline
        ):
            self.calls.poll()
        self.assertIsNone(self.calls._handover.pending)
        self.assertEqual(self.starts(), [])

    def test_clear_does_not_issue_duplicate_inflight_exact_hangup(self) -> None:
        """Activation teardown cancels continuation while the already admitted end resolves once."""
        self.begin()
        with patch('metor.ui.gui.runtime.calls.controller.threading.Thread') as thread:
            self.calls.clear()
        thread.assert_not_called()
        self.gui.client.hangup_call.assert_called_once_with('old')
        self.assertIsNone(self.calls._handover.pending)
        self.assertEqual(self.starts(), [])

    def test_show_reopens_only_current_call_without_new_request(self) -> None:
        """The same-peer In call action uses existing controls without starting a second Call."""
        self.calls.visible = False
        self.assertFalse(self.calls.show('replacement'))
        self.assertTrue(self.calls.show('old'))
        self.assertTrue(self.calls.visible)
        self.assertEqual(self.operations, [])
        self.calls.current = self.ended
        self.assertFalse(self.calls.show('old'))
        self.calls.current = replace(self.old, owned=False)
        self.assertFalse(self.calls.show('old'))


class CallHandoverIpcTests(unittest.TestCase):
    """Production SDK stamps and ended ownership satisfy the guarded replacement proof."""

    def test_protected_ipc_unknown_end_read_keeps_owned_active_call_reachable(
        self,
    ) -> None:
        """A real status read resolves a lost End request without abandoning or replacing its Call."""
        h = support.CallIntegrationTests()
        h.setUp()
        self.addCleanup(h.doCleanups)
        target = _onion(9)
        h.sender.contacts.ensure_alias_for_onion(target)
        h._active_call('gui-uncertain')
        snapshot, states = (
            h.sender.client.runtime_snapshot(),
            h.sender.client.get_calls(),
        )
        self.assertIsInstance(snapshot, RuntimeSnapshotEvent)
        self.assertIsInstance(states, CallsStateEvent)
        old = next(item for item in states.calls if item.call_id == 'gui-uncertain')
        gui = GuiController(FrontendLaunchContext('fixture', Mock()), simulator=True)
        gui.simulator = False
        gui.client = h.sender.client
        gui.state.covered = False
        gui.state.capabilities = frozenset({'calls'})
        gui.state.snapshot = snapshot
        gui.voice.configure(HeadsetAudio(1, 2), headset_confirmed=True)
        gui.voice.routes.input, gui.voice.routes.output = 1, 2
        operations: list[tuple[str, Callable[[], IpcEvent | None]]] = []

        def submit(
            operation: str,
            work: Callable[[], IpcEvent | None],
            *,
            background: bool = False,
        ) -> bool:
            """Retains public requests; the End is deliberately lost before reaching Core."""
            operations.append((operation, work))
            return True

        gui.submit = submit
        gui.calls.current = old
        self.assertTrue(gui.calls.handover(old.call_id, target))
        gui.calls.install(Update(0, operations[-1][0]))
        gui.calls.poll()
        operation, read = operations[-1]
        self.assertTrue(operation.startswith('call-reconcile:end:'))
        proof = read()
        self.assertIsInstance(proof, CallsStateEvent)
        self.assertEqual(proof.epoch, snapshot.epoch)
        self.assertGreater(proof.revision, snapshot.revision)
        confirmed = next(item for item in proof.calls if item.call_id == old.call_id)
        self.assertTrue(confirmed.owned)
        self.assertIs(confirmed.state, CallState.ACTIVE)
        gui.calls.install(Update(0, operation, proof))
        with patch('metor.ui.gui.runtime.calls.controller.CallMediaWorker') as worker:
            gui.calls.poll()
            worker.assert_called_once()
        self.assertEqual(gui.calls.current.call_id, old.call_id)
        self.assertTrue(gui.calls.show(old.call_id))
        self.assertFalse(any(item[0].startswith('call:start:') for item in operations))
        self.assertIsNone(gui.calls._handover.pending)
        self.assertEqual(h.sender.tor.connect.call_count, 1)

    def test_protected_ipc_positive_end_fresh_read_and_target_start(self) -> None:
        """Actual Core hangup/get_calls/start obey revision, ownership and activation fences."""
        h = support.CallIntegrationTests()
        h.setUp()
        self.addCleanup(h.doCleanups)
        h.events['target'] = []
        target = h._peer('target')
        h.sender.contacts.ensure_alias_for_onion(target.onion)
        target.contacts.ensure_alias_for_onion(h.sender.onion)
        h.sender.tor.connect.side_effect = lambda peer: h._dial(
            target if peer == target.onion else h.receiver, peer
        )
        h._active_call('gui-old')
        snapshot = h.sender.client.runtime_snapshot()
        self.assertIsInstance(snapshot, RuntimeSnapshotEvent)
        self.assertTrue(snapshot.profile_instance_id)
        states = h.sender.client.get_calls()
        self.assertIsInstance(states, CallsStateEvent)
        old = next(item for item in states.calls if item.call_id == 'gui-old')
        gui = GuiController(FrontendLaunchContext('fixture', Mock()), simulator=True)
        gui.simulator = False
        gui.client = h.sender.client
        gui.state.covered = False
        gui.state.capabilities = frozenset({'calls'})
        gui.state.snapshot = snapshot
        gui.state.route = Route('V08', h.receiver.onion)
        gui.voice.configure(HeadsetAudio(1, 2), headset_confirmed=True)
        gui.voice.routes.input, gui.voice.routes.output = 1, 2
        operations: list[tuple[str, Callable[[], IpcEvent | None]]] = []

        def submit(
            operation: str,
            work: Callable[[], IpcEvent | None],
            *,
            background: bool = False,
        ) -> bool:
            """Executes each captured public request explicitly without allocating native streams."""
            operations.append((operation, work))
            return True

        gui.submit = submit
        gui.calls.current = old
        self.assertTrue(gui.calls.handover(old.call_id, target.onion))
        end_operation, end = operations[-1]
        ended = end()
        self.assertIsInstance(ended, CallStateEvent)
        self.assertEqual(ended.epoch, snapshot.epoch)
        self.assertGreaterEqual(ended.revision, snapshot.revision)
        self.assertEqual(ended.call.call_id, old.call_id)
        self.assertIs(ended.call.state, CallState.ENDED)
        self.assertTrue(ended.call.owned)
        gui.calls.install(Update(0, end_operation, ended))
        gui.calls.poll()
        read_operation, read = operations[-1]
        self.assertTrue(read_operation.startswith('call-handover:read:'))
        fresh = read()
        self.assertIsInstance(fresh, CallsStateEvent)
        self.assertEqual(fresh.epoch, ended.epoch)
        self.assertGreater(fresh.revision, ended.revision)
        self.assertTrue(all(item.state is CallState.ENDED for item in fresh.calls))
        gui.calls.install(Update(0, read_operation, fresh))
        gui.calls.poll()
        starts = [item for item in operations if item[0].startswith('call:start:')]
        self.assertEqual(len(starts), 1)
        start_operation, start = starts[0]
        outgoing = start()
        self.assertIsInstance(outgoing, CallStateEvent)
        self.assertEqual(outgoing.call.peer, target.onion)
        self.assertTrue(outgoing.call.owned)
        gui.calls.install(Update(0, start_operation, outgoing))
        gui.calls.install(Update(0, read_operation, fresh))
        gui.calls.poll()
        self.assertEqual(
            len([item for item in operations if item[0].startswith('call:start:')]), 1
        )
        self.assertEqual(gui.state.route.peer, h.receiver.onion)
        self.assertIsNone(gui.calls.worker)


if __name__ == '__main__':
    unittest.main()
