"""Protected GUI editor revisions across another client's concurrent policy change."""

from dataclasses import replace
import unittest
from unittest.mock import Mock, patch

import test_gui_producers as support
from metor.client import FrontendLaunchContext
from metor.core.api import (
    GetGuiPreferencesCommand,
    GuiPreferencesEvent,
    SetGuiPreferencesCommand,
    GetConfigListCommand,
    ConfigListDataEvent,
    SetConfigCommand,
    ConfigUpdatedEvent,
    IpcEvent,
    InvalidConfigKeyEvent,
    BeginVoiceCommand,
    Delivery,
    DropsDisabledEvent,
    SendMessageCommand,
    TextContent,
    VoiceCommittedEvent,
)
from metor.data import SettingKey, Settings
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update


class SettingsCoreTests(unittest.TestCase):
    """Verifies stale native-form intent through two actual encrypted Core clients."""

    def test_covered_late_descriptors_require_fresh_authorized_read(self) -> None:
        """A pending pre-lock settings response cannot repopulate private values.

        Args:
            None
        Returns:
            None
        """
        gui = GuiController(FrontendLaunchContext('fixture', Mock()))
        self.addCleanup(gui.close)
        gui.state.covered = True
        gui.core_settings.install(
            Update(
                gui.state.generation,
                'core-settings:read',
                ConfigListDataEvent('daemon', 'fixture', []),
            )
        )
        self.assertFalse(gui.core_settings.loaded)
        self.assertFalse(gui.core_settings.last_read_success)
        self.assertTrue(gui.core_settings.refresh_needed)
        self.assertEqual(gui.core_settings.entries, ())

    def test_stale_editor_cannot_overwrite_a_newer_unrelated_preference(self) -> None:
        """Keeps the other client's value and displays a conflict after rehydration.

        Args:
            None
        Returns:
            None
        """
        h = support.GuiProducerTests()
        h.setUp()
        self.addCleanup(h.doCleanups)
        gui = GuiController(FrontendLaunchContext('voice-owned', Mock()))
        self.addCleanup(gui.close)
        gui.client = h.client
        gui.state.covered = False
        gui.state.route = Route('V17')
        gui.state.snapshot = h.client.runtime_snapshot()
        displayed = h.client.request(GetGuiPreferencesCommand(), GuiPreferencesEvent)
        gui.state.preferences = displayed
        newer = h.other.request(
            SetGuiPreferencesCommand(
                displayed.preferences_revision,
                replace(displayed.preferences, auto_play=True),
            ),
            GuiPreferencesEvent,
        )
        gui.preferences.install(newer)
        self.assertTrue(
            gui.preferences.save(
                replace(displayed.preferences, idle_seconds=300),
                displayed.preferences_revision,
            )
        )
        for _ in range(8):
            if gui._worker is not None:
                gui._worker.join(5)
            gui.poll()
            if not gui.state.busy and not gui.preferences.refresh_needed:
                break
        current = h.client.request(GetGuiPreferencesCommand(), GuiPreferencesEvent)
        self.assertTrue(current.preferences.auto_play)
        self.assertEqual(
            current.preferences.idle_seconds, displayed.preferences.idle_seconds
        )
        self.assertEqual(
            gui.state.preferences.preferences_revision, current.preferences_revision
        )
        self.assertIn('changed elsewhere', gui.state.status)

    def test_safe_descriptors_and_stale_profile_override_preserve_other_values(
        self,
    ) -> None:
        """Reads actual descriptors and rejects a stale save without changing global policy.

        Args:
            None
        Returns:
            None
        """
        h = support.GuiProducerTests()
        h.setUp()
        self.addCleanup(h.doCleanups)
        gui = GuiController(FrontendLaunchContext('voice-owned', Mock()))
        self.addCleanup(gui.close)
        gui.client = h.client
        gui.state.covered = False
        gui.state.capabilities = frozenset(h.client.init_event.capabilities)
        gui.state.route = Route('V17')
        gui.state.snapshot = h.client.runtime_snapshot()
        gui.core_settings.poll()
        self.settle(gui)
        by_key = {row.key: row for row in gui.core_settings.entries}
        self.assertTrue(gui.core_settings.loaded)
        self.assertNotIn(SettingKey.ENABLE_SQL_LOGGING.value, by_key)
        self.assertNotIn(SettingKey.ENABLE_RUNTIME_DB_MIRROR.value, by_key)
        self.assertNotIn(SettingKey.REQUIRE_LOCAL_AUTH.value, by_key)
        self.assertNotIn(SettingKey.ALLOW_PLAINTEXT_PROFILES.value, by_key)
        row = by_key[SettingKey.MAX_PENDING_LIVE_MSGS.value]
        self.assertEqual(row.value_type, 'int')
        self.assertEqual(
            row.min_value, Settings.get_spec(SettingKey.MAX_PENDING_LIVE_MSGS).min_value
        )
        self.assertEqual(row.scope, 'profile')
        self.assertIn(
            'recording starts', by_key[SettingKey.ALLOW_DROPS.value].description
        )
        global_value = Settings.get(SettingKey.MAX_PENDING_LIVE_MSGS)
        self.assertIsNotNone(
            h.other.request(SetConfigCommand(row.key, 42), ConfigUpdatedEvent)
        )
        self.assertIsNotNone(gui.core_settings.save(row, 43))
        self.settle(gui)
        self.assertFalse(gui.core_settings.completed_success)
        self.assertIn('changed elsewhere', gui.core_settings.error)
        current = next(
            item for item in gui.core_settings.entries if item.key == row.key
        )
        self.assertEqual(current.value, '42')
        self.assertEqual(current.source, 'profile_override')
        self.assertEqual(Settings.get(SettingKey.MAX_PENDING_LIVE_MSGS), global_value)
        denied = h.client.request(
            SetConfigCommand(SettingKey.ENABLE_SQL_LOGGING.value, True, safe_only=True),
            IpcEvent,
        )
        self.assertIsInstance(denied, InvalidConfigKeyEvent)
        self.assertFalse(h.pm.config.get_bool(SettingKey.ENABLE_SQL_LOGGING))
        h.capture('existing-review')
        self.assertIsNotNone(
            h.client.finalize_voice('existing-review', 20, owner_token=h.owner)
        )
        self.assertIsNotNone(
            h.client.request(
                SetConfigCommand(SettingKey.ALLOW_DROPS.value, False),
                ConfigUpdatedEvent,
            )
        )
        refused_text = h.client.request(
            SendMessageCommand(h.onion, Delivery.DROP, TextContent('new'), 'new-text'),
            IpcEvent,
        )
        self.assertIsInstance(refused_text, DropsDisabledEvent)
        refused_recording = h.other.request(
            BeginVoiceCommand(
                h.onion, Delivery.DROP, 'new-recording', 'pcm_s16le_16000_mono'
            ),
            IpcEvent,
        )
        self.assertIsInstance(refused_recording, DropsDisabledEvent)
        self.assertIsInstance(
            h.client.commit_voice(h.onion, 'existing-review', owner_token=h.owner),
            VoiceCommittedEvent,
        )

    def test_unknown_setting_save_rechecks_without_repeating(self) -> None:
        """A lost response retains the actual value and performs no duplicate update.

        Args:
            None
        Returns:
            None
        """
        h = support.GuiProducerTests()
        h.setUp()
        self.addCleanup(h.doCleanups)
        gui = GuiController(FrontendLaunchContext('voice-owned', Mock()))
        self.addCleanup(gui.close)
        gui.client = h.client
        gui.state.covered = False
        gui.state.capabilities = frozenset(h.client.init_event.capabilities)
        gui.state.route = Route('V17')
        gui.state.snapshot = h.client.runtime_snapshot()
        event = h.client.request(
            GetConfigListCommand(safe_descriptors=True), ConfigListDataEvent
        )
        row = next(
            item
            for item in event.entries
            if item.key == SettingKey.SEND_READ_RECEIPTS.value
        )
        original = h.client.request
        writes = []

        def lost(command: object, expected: object) -> IpcEvent | None:
            """Hides only the response after the real config write.

            Args:
                command: Public command under test.
                expected: Original typed result expectation.
            Returns:
                IpcEvent | None: Actual read response or lost write result.
            """
            result = original(command, expected)
            if isinstance(command, SetConfigCommand):
                writes.append(command)
                return None
            return result

        with patch.object(h.client, 'request', side_effect=lost):
            self.assertIsNotNone(gui.core_settings.save(row, True))
            self.assertIsNone(gui.core_settings.save(row, True))
            self.settle(gui)
        self.assertEqual(len(writes), 1)
        self.assertIsNone(gui.core_settings.pending)
        current = next(
            item for item in gui.core_settings.entries if item.key == row.key
        )
        self.assertEqual(current.value, 'True')
        self.assertIn('unconfirmed', gui.core_settings.error)
        self.assertTrue(h.pm.config.get_bool(SettingKey.SEND_READ_RECEIPTS))

    def test_unknown_gui_preference_save_allows_new_intent_only_after_readback(
        self,
    ) -> None:
        """A failed read keeps the duplicate barrier; explicit successful readback releases it.

        Args:
            None
        Returns:
            None
        """
        h = support.GuiProducerTests()
        h.setUp()
        self.addCleanup(h.doCleanups)
        gui = GuiController(FrontendLaunchContext('voice-owned', Mock()))
        self.addCleanup(gui.close)
        gui.client = h.client
        gui.state.covered = False
        gui.state.route = Route('V17')
        gui.state.snapshot = h.client.runtime_snapshot()
        displayed = h.client.request(GetGuiPreferencesCommand(), GuiPreferencesEvent)
        gui.preferences.install(displayed)
        original = h.client.request
        writes, failed_reads = [], []

        def lost(command: object, expected: object) -> IpcEvent | None:
            """Loses one committed response and its first metadata read, preserving real writes.

            Args:
                command: Captured public request.
                expected: Original typed expectation.
            Returns:
                IpcEvent | None: Actual response or deliberately unconfirmed result.
            """
            result = original(command, expected)
            if isinstance(command, SetGuiPreferencesCommand):
                writes.append(command)
                if len(writes) == 1:
                    return None
            if isinstance(command, GetGuiPreferencesCommand) and not failed_reads:
                failed_reads.append(command)
                return None
            return result

        with patch.object(h.client, 'request', side_effect=lost):
            proposed = replace(displayed.preferences, auto_play=True)
            self.assertTrue(
                gui.preferences.save(proposed, displayed.preferences_revision)
            )
            for _ in range(4):
                if gui._worker is not None:
                    gui._worker.join(5)
                gui.poll()
            self.assertFalse(gui.state.preferences.preferences.auto_play)
            self.assertFalse(
                gui.preferences.save(proposed, displayed.preferences_revision)
            )
            self.assertEqual(len(writes), 1)
            gui.preferences.refresh_needed = True
            gui.poll()
            for _ in range(4):
                if gui._worker is not None:
                    gui._worker.join(5)
                gui.poll()
            self.assertTrue(gui.state.preferences.preferences.auto_play)
            self.assertIn('unconfirmed', gui.state.status)
            current = gui.state.preferences
            self.assertTrue(
                gui.preferences.save(
                    replace(current.preferences, auto_play=False),
                    current.preferences_revision,
                )
            )
            if gui._worker is not None:
                gui._worker.join(5)
            gui.poll()
        self.assertEqual(len(writes), 2)
        self.assertFalse(gui.state.preferences.preferences.auto_play)

    def settle(self, gui: GuiController) -> None:
        """Waits for finite local writes and their authoritative descriptor readback.

        Args:
            gui: Active real GUI coordinator.
        Returns:
            None
        """
        for _ in range(8):
            if gui._worker is not None:
                gui._worker.join(5)
                self.assertFalse(gui._worker.is_alive())
            gui.poll()
            if not gui.state.busy and not gui.core_settings.refresh_needed:
                break
