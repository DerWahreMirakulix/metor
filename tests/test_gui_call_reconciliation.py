"""Unknown End recovery preserves exact Call reachability without reviving replacement intent."""

from dataclasses import replace
import unittest
from unittest.mock import Mock, patch

import test_gui_call_handover as support
from metor.core.api import CallInfo, CallState, CallStateEvent, CallsStateEvent
from metor.ui.gui.state.mailbox import Update


class CallEndReconciliationTests(unittest.TestCase):
    """Fresh qualified status reads separate end uncertainty from actual native media failure."""

    def setUp(self) -> None:
        """Uses production CallActions and the shared canonical-identity request fixture."""
        self.h = support.CallHandoverTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.gui, self.calls = self.h.gui, self.h.calls

    def unknown_end(self) -> str:
        """Cancels replacement after an uncertain end and captures its later exact read."""
        operation = self.h.begin()
        self.calls.install(Update(0, operation))
        self.assertIsNone(self.calls._handover.pending)
        self.calls.poll()
        read_operation, read = self.h.operations[-1]
        self.assertTrue(read_operation.startswith('call-reconcile:end:'))
        read()
        return read_operation

    def proof(self, operation: str) -> Update:
        """Returns newer owned original-call state for the exact post-outcome read."""
        return Update(
            0,
            operation,
            CallsStateEvent([self.h.old], epoch='epoch', revision=12),
            background=True,
        )

    def test_fresh_owned_active_proof_restores_old_audio_and_controls_without_new_call(
        self,
    ) -> None:
        """Uncertain hangup does not abandon a still-active Call or auto-call the replacement."""
        operation = self.unknown_end()
        self.calls.install(
            Update(
                0,
                'call-snapshot',
                CallsStateEvent([self.h.old], epoch='epoch', revision=12),
            )
        )
        with patch('metor.ui.gui.runtime.calls.controller.CallMediaWorker') as worker:
            self.calls.poll()
            worker.assert_not_called()
            self.calls.install(self.proof(operation))
            self.calls.poll()
            worker.assert_called_once()
            worker.return_value.start.assert_called_once()
        self.assertIs(self.calls.current, self.h.old)
        self.assertTrue(self.calls.show('old'))
        self.assertIsNone(self.calls._checking_id)
        self.assertIsNone(self.calls._ending_id)
        self.assertEqual(self.h.starts(), [])
        self.assertTrue(self.calls.end())
        self.h.operations[-1][1]()
        self.assertEqual(self.gui.client.hangup_call.call_count, 2)

    def test_real_media_failure_is_not_lifted_by_owned_active_end_proof(self) -> None:
        """A true failed native route stays suppressed even when the Call itself remains active."""
        operation = self.unknown_end()
        self.calls.install(
            Update(0, 'call-media-error:old', status='Audio device failed')
        )
        self.calls.install(self.proof(operation))
        with patch('metor.ui.gui.runtime.calls.controller.CallMediaWorker') as worker:
            self.calls.poll()
        worker.assert_not_called()
        self.assertEqual(self.calls._media_failed_id, 'old')
        self.assertTrue(self.calls.show('old'))
        self.assertEqual(self.h.starts(), [])

    def test_stale_epoch_revision_mutation_and_identity_proofs_cannot_resume_audio(
        self,
    ) -> None:
        """A generic/pre-End or misqualified read cannot lift the exact pending-end fence."""
        for change in (
            'operation',
            'generation',
            'epoch',
            'revision',
            'read_epoch',
            'peer',
            'owner',
            'replacement',
            'unknown',
        ):
            with self.subTest(change=change):
                self.setUp()
                operation = self.unknown_end()
                update = self.proof(operation)
                if change == 'operation':
                    update = replace(update, operation='call-snapshot')
                elif change == 'generation':
                    update = replace(update, generation=-1)
                elif change == 'epoch':
                    update.event.epoch = 'replacement'
                elif change == 'revision':
                    update.event.revision = 10
                elif change == 'read_epoch':
                    self.gui._operations.invalidate_reads()
                    update = replace(update, read_epoch=0)
                elif change == 'peer':
                    update.event.calls = [replace(self.h.old, peer=self.h.target)]
                elif change == 'owner':
                    update.event.calls = [replace(self.h.old, owned=False)]
                elif change == 'replacement':
                    update.event.calls.append(
                        CallInfo('other', self.h.target, 'Target', CallState.INCOMING)
                    )
                else:
                    update = replace(update, event=None)
                self.calls.install(update)
                with patch(
                    'metor.ui.gui.runtime.calls.controller.CallMediaWorker'
                ) as worker:
                    self.calls.poll()
                worker.assert_not_called()
                self.assertEqual(self.calls._ending_id, 'old')
                self.assertEqual(self.h.starts(), [])

    def test_cover_client_and_profile_replacement_revoke_old_read(self) -> None:
        """No pending-read result can restore native media after the original activation leaves."""
        for change in ('cover', 'client', 'instance', 'epoch', 'generation'):
            with self.subTest(change=change):
                self.setUp()
                operation = self.unknown_end()
                if change == 'cover':
                    self.gui.state.covered = True
                    self.calls.cover()
                    self.gui.state.covered = False
                elif change == 'client':
                    self.gui.client = Mock()
                elif change == 'instance':
                    self.gui.state.snapshot.profile_instance_id = 'replacement'
                elif change == 'epoch':
                    self.gui.state.snapshot.epoch = 'replacement'
                else:
                    self.gui.state.generation += 1
                self.calls.install(self.proof(operation))
                with patch(
                    'metor.ui.gui.runtime.calls.controller.CallMediaWorker'
                ) as worker:
                    self.calls.poll()
                worker.assert_not_called()
                self.assertEqual(self.h.starts(), [])

    def test_later_ended_event_prevents_read_from_resurrecting_old_call(self) -> None:
        """An older active read cannot undo the original Call's later confirmed termination."""
        operation = self.unknown_end()
        self.calls.observe(CallStateEvent(self.h.ended, epoch='epoch', revision=13))
        self.calls.install(self.proof(operation))
        with patch('metor.ui.gui.runtime.calls.controller.CallMediaWorker') as worker:
            self.calls.poll()
        worker.assert_not_called()
        self.assertIs(self.calls.current.state, CallState.ENDED)
        self.assertEqual(self.h.starts(), [])

    def test_unknown_end_read_can_confirm_ended_without_starting_replacement(
        self,
    ) -> None:
        """Positive later status resolves end uncertainty while the earlier continuation stays canceled."""
        operation = self.unknown_end()
        self.calls.install(
            Update(
                0,
                operation,
                CallsStateEvent([self.h.ended], epoch='epoch', revision=12),
            )
        )
        self.calls.poll()
        self.assertIs(self.calls.current.state, CallState.ENDED)
        self.assertIsNone(self.calls._checking_id)
        self.assertEqual(self.h.starts(), [])

    def test_rejected_end_admission_does_not_stop_current_media(self) -> None:
        """A busy UI cannot suppress a Call unless its exact end request was admitted."""
        worker = Mock(done=Mock(is_set=lambda: False))
        self.calls.worker = worker
        self.gui.submit = Mock(return_value=False)
        self.assertFalse(self.calls.end())
        worker.stop.assert_not_called()
        self.assertIsNone(self.calls._ending_id)
        self.assertEqual(self.h.operations, [])

    def test_bar_mute_and_end_preserve_explicit_overlay_visibility_when_locked(
        self,
    ) -> None:
        """Bar controls stay compact; opening exact controls remains an explicit independent choice."""
        for expanded in (False, True):
            with self.subTest(expanded=expanded):
                self.setUp()
                self.gui.state.covered = True
                self.calls.cover()
                if expanded:
                    self.assertTrue(self.calls.show('old'))
                self.assertTrue(self.calls.mute())
                operation = self.h.operations[-1][0]
                self.assertEqual(self.calls.visible, expanded)
                self.calls.install(
                    Update(
                        0,
                        operation,
                        CallStateEvent(
                            replace(self.h.old, muted=True), epoch='epoch', revision=11
                        ),
                    )
                )
                self.assertEqual(self.calls.visible, expanded)
                self.assertTrue(self.calls.end())
                operation = self.h.operations[-1][0]
                self.assertEqual(self.calls.visible, expanded)
                self.calls.install(
                    Update(
                        0,
                        operation,
                        CallStateEvent(self.h.ended, epoch='epoch', revision=12),
                    )
                )
                self.assertEqual(self.calls.visible, expanded)


if __name__ == '__main__':
    unittest.main()
