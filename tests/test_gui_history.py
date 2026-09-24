"""Real encrypted Core history paging, metadata boundaries and uncertain GUI clears."""

import unittest
from unittest.mock import Mock, patch

import test_gui_producers as support
from metor.client import FrontendProfileState
from metor.client import FrontendLaunchContext
from metor.core.api import (
    ClearHistoryCommand,
    GetHistoryCommand,
    GetRawHistoryCommand,
    HistoryDataEvent,
    HistoryRawDataEvent,
    IpcEvent,
    MessageDirectionCode,
)
from metor.data import SettingKey
from metor.data.history import HistoryActor, HistoryEvent, HistoryFamily
from metor.shared import Constants
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update


class GuiHistoryTests(unittest.TestCase):
    """Exercises actual ledger storage and SDK transport without peer traffic."""

    def harness(self) -> support.GuiProducerTests:
        """Creates an isolated protected runtime with existing cleanup ownership.

        Args:
            None
        Returns:
            GuiProducerTests: Two authenticated SDK clients and encrypted storage.
        """
        h = support.GuiProducerTests()
        h.setUp()
        self.addCleanup(h.doCleanups)
        return h

    def populate(
        self, h: support.GuiProducerTests, count: int, noise: bool = False
    ) -> None:
        """Writes equal-timestamp ledger fixtures to test the identity tie breaker.

        Args:
            h: Isolated Core harness.
            count: Number of accepted metadata entries.
            noise: Whether to create technical-only transport rows.
        Returns:
            None
        """
        repository = h.daemon._hm._history
        for index in range(count):
            repository.log_entry(
                timestamp='2026-09-12T10:00:00+00:00',
                family=HistoryFamily.DROP,
                event_code=HistoryEvent.TUNNEL_CLOSED if noise else HistoryEvent.SENT,
                peer_onion=h.onion,
                actor=HistoryActor.LOCAL,
                trigger=None,
                detail_code=None,
                detail_text='PRIVATE DIAGNOSTIC CONTENT' * 1000,
                flow_id=str(index),
                transport='drop',
            )

    def test_pages_are_bounded_and_stable_across_arrival_and_deleted_anchor(
        self,
    ) -> None:
        """Walks 130 equal-timestamp rows without duplication or diagnostic export.

        Args:
            None
        Returns:
            None
        """
        h = self.harness()
        self.populate(h, 130)
        h.pm.config.set(SettingKey.RECORD_DROP_HISTORY, False)
        h.pm.config.set(SettingKey.RECORD_LIVE_HISTORY, False)
        first = h.client.request(GetHistoryCommand(page_size=64), HistoryDataEvent)
        self.assertEqual(len(first.entries), 64)
        self.assertTrue(first.metadata_only)
        self.assertFalse(first.record_live)
        self.assertFalse(first.record_drop)
        self.assertNotIn('PRIVATE DIAGNOSTIC', first.to_json())
        self.assertTrue(all(entry.detail_text == '' for entry in first.entries))
        self.populate(h, 1)
        second = h.client.request(
            GetHistoryCommand(page_size=64, before_id=first.next_before_id),
            HistoryDataEvent,
        )
        third = h.client.request(
            GetHistoryCommand(page_size=64, before_id=second.next_before_id),
            HistoryDataEvent,
        )
        self.assertEqual((len(second.entries), len(third.entries)), (64, 2))
        self.assertFalse(third.has_older)
        self.assertIsNone(third.next_before_id)
        self.assertEqual(
            [
                entry.flow_id
                for page in (first, second, third)
                for entry in page.entries
            ],
            [str(index) for index in reversed(range(130))],
        )
        h.other.request(ClearHistoryCommand(), IpcEvent)
        missing = h.client.request(
            GetHistoryCommand(page_size=64, before_id=first.next_before_id),
            HistoryDataEvent,
        )
        self.assertFalse(missing.page_available)
        self.assertEqual(missing.entries, [])
        fresh = h.client.request(GetHistoryCommand(page_size=64), HistoryDataEvent)
        self.assertTrue(fresh.page_available)
        self.assertEqual(fresh.entries, [])

    def test_summary_noise_page_has_truthful_continuation_and_raw_metadata(
        self,
    ) -> None:
        """A raw-only page never causes an unbounded scan or false end of history.

        Args:
            None
        Returns:
            None
        """
        h = self.harness()
        self.populate(h, 1)
        self.populate(h, 2, noise=True)
        first = h.client.request(GetHistoryCommand(page_size=2), HistoryDataEvent)
        self.assertEqual(first.entries, [])
        self.assertTrue(first.has_older)
        second = h.client.request(
            GetHistoryCommand(page_size=2, before_id=first.next_before_id),
            HistoryDataEvent,
        )
        self.assertEqual(len(second.entries), 1)
        raw = h.client.request(GetRawHistoryCommand(page_size=2), HistoryRawDataEvent)
        self.assertEqual(len(raw.entries), 2)
        self.assertNotIn('PRIVATE DIAGNOSTIC', raw.to_json())
        legacy = h.client.request(GetRawHistoryCommand(limit=1), HistoryRawDataEvent)
        self.assertFalse(legacy.metadata_only)
        self.assertIn('PRIVATE DIAGNOSTIC', legacy.entries[0].detail_text)

    def test_unknown_clear_rechecks_once_preserving_messages_and_covered_privacy(
        self,
    ) -> None:
        """A lost actual clear response causes a read, never a repeated destruction.

        Args:
            None
        Returns:
            None
        """
        h = self.harness()
        self.populate(h, 2)
        retained = h.capture('retained-review')
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
        gui.client = h.client
        gui.state.capabilities = frozenset(h.client.init_event.capabilities)
        gui.state.covered = False
        gui.state.route = Route('V18')
        gui.history.poll()
        self.settle(gui)
        old_page = gui.history.page
        self.assertEqual(len(old_page.entries), 2)
        original = h.client.request
        writes = []
        failed_reads = []

        def lost(command: object, expected: object) -> IpcEvent | None:
            """Loses the mutation response after Core has actually cleared its ledger.

            Args:
                command: Original public command.
                expected: Typed SDK expectation.
            Returns:
                IpcEvent | None: Read response or hidden completed mutation.
            """
            result = original(command, expected)
            if isinstance(command, ClearHistoryCommand):
                writes.append(command)
                return None
            if isinstance(command, GetHistoryCommand) and writes and not failed_reads:
                failed_reads.append(command)
                return None
            return result

        with patch.object(h.client, 'request', side_effect=lost):
            self.assertTrue(gui.history.clear())
            self.assertFalse(gui.history.clear())
            self.settle(gui)
            self.assertIs(gui.history.page, old_page)
            self.assertTrue(gui.history.pending)
            gui.history.move('first')
            gui.history.poll()
            self.settle(gui)
        self.assertEqual(len(writes), 1)
        self.assertEqual(gui.history.page.entries, [])
        self.assertIn('unconfirmed', gui.history.error)
        self.assertFalse(gui.history.pending)
        self.assertIsNotNone(
            h.client.get_voice_chunk(
                h.onion,
                'retained-review',
                MessageDirectionCode.OUT,
                0,
                640,
                owner_token=h.owner,
            )
        )
        self.assertTrue(retained)
        gui.history._read = 'history:read:late'
        gui.state.covered = True
        gui.history.cover()
        gui.history.install(Update(gui.state.generation, 'history:read:late', old_page))
        self.assertIsNone(gui.history.page)
        self.assertTrue(gui.history.needed)

    def test_invalid_paging_is_rejected_before_sql(self) -> None:
        """Rejects Boolean, oversized and legacy-mixed paging requests.

        Args:
            None
        Returns:
            None
        """
        for command in (GetHistoryCommand, GetRawHistoryCommand):
            for kwargs in (
                {'page_size': True},
                {'page_size': 201},
                {'before_id': 1},
                {'page_size': 1, 'limit': 2},
                {'page_size': 1, 'before_id': Constants.HISTORY_ANCHOR_MAX + 1},
            ):
                with (
                    self.subTest(command=command, kwargs=kwargs),
                    self.assertRaises(ValueError),
                ):
                    command(**kwargs)

    def settle(self, gui: GuiController) -> None:
        """Drains finite GUI SDK operations without network activity or sleeps.

        Args:
            gui: Controller with one isolated real SDK client.
        Returns:
            None
        """
        for _ in range(8):
            if gui._worker is not None:
                gui._worker.join(5)
                self.assertFalse(gui._worker.is_alive())
            gui.poll()
            if not gui.state.busy and not gui.history.needed:
                break
