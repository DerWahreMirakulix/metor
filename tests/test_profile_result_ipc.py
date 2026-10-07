"""Actual headless IPC retains every valid profile result, including partial success."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from metor.client import IpcClient
from metor.core.api import (
    AddProfileCommand,
    IpcCommand,
    MigrateProfileSecurityCommand,
    ProfileOperationCode,
    ProfileOperationResultEvent,
    RenameProfileCommand,
)
from metor.core.daemon.headless import HeadlessDaemon
from metor.core.daemon.handlers import ProfileCommandHandler
from metor.data import SettingKey, Settings
from metor.data.profile import ProfileManager, ProfileOperationResult
from metor.data.profile.models import ProfileOperationType
from metor.utils import Constants


class ProfileResultIpcTests(unittest.TestCase):
    """Exercise typed result conversion and actual offline Core lifecycle commands."""

    def setUp(self) -> None:
        """Give all profile operations an empty isolated protected catalog."""
        temporary = TemporaryDirectory(prefix='metor-profile-result-ipc-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        data = patch.object(Constants, 'DATA', root)
        data.start()
        self.addCleanup(data.stop)
        self.profile = ProfileManager('headless-result')

    def exchange(self, command: IpcCommand) -> ProfileOperationResultEvent:
        """Send one actual NDJSON command to the production ephemeral daemon."""
        with HeadlessDaemon(self.profile) as daemon:
            client = IpcClient(
                daemon.port,
                timeout=Constants.DEFAULT_IPC_TIMEOUT,
                on_event=lambda _event: None,
                on_disconnect=lambda: None,
            )
            try:
                self.assertTrue(client.connect(start_listener=False))
                client.send_command(command)
                event = client.read_event(Constants.DEFAULT_IPC_TIMEOUT)
                self.assertIsInstance(event, ProfileOperationResultEvent)
                assert isinstance(event, ProfileOperationResultEvent)
                return event
            finally:
                client.stop()

    def test_every_domain_profile_result_has_a_strict_roundtrip_code(self) -> None:
        """Valid domain outcomes never collapse into internal-error IPC replies."""
        for operation_type in ProfileOperationType:
            with self.subTest(code=operation_type.value):
                result = ProfileOperationResult(False, operation_type, {})
                event = ProfileCommandHandler._build_result_event(result)
                self.assertEqual(event.operation_type.value, operation_type.value)
                decoded = ProfileOperationResultEvent.from_dict(
                    json.loads(event.to_json())
                )
                self.assertEqual(decoded, event)

    def test_disabled_plaintext_creation_and_migration_return_typed_refusal(
        self,
    ) -> None:
        """Actual policy refusal names the cause and does not create plaintext data."""
        self.assertFalse(Settings.get_bool(SettingKey.ALLOW_PLAINTEXT_PROFILES))
        created = self.exchange(
            AddProfileCommand('plaintext-refused', security_mode='plaintext')
        )
        self.assertFalse(created.success)
        self.assertEqual(
            created.operation_type, ProfileOperationCode.PLAINTEXT_PROFILES_DISABLED
        )
        self.assertFalse(ProfileManager('plaintext-refused').exists())
        self.assertTrue(
            ProfileManager.add_profile_folder(
                'encrypted-source', master_password='disposable-test-password'
            ).success
        )
        migrated = self.exchange(
            MigrateProfileSecurityCommand(
                'encrypted-source',
                'plaintext',
                current_password='disposable-test-password',
            )
        )
        self.assertFalse(migrated.success)
        self.assertEqual(
            migrated.operation_type,
            ProfileOperationCode.PLAINTEXT_PROFILES_DISABLED,
        )
        self.assertTrue(ProfileManager('encrypted-source').uses_encrypted_storage())

    def test_completed_rename_with_failed_default_write_is_not_internal_error(
        self,
    ) -> None:
        """A real renamed directory survives an injected catalog-settings write failure."""
        self.assertTrue(
            ProfileManager.add_profile_folder(
                'old-default', master_password='disposable-test-password'
            ).success
        )
        self.assertTrue(ProfileManager.set_default_profile('old-default').success)
        with patch.object(
            Settings, 'set', side_effect=OSError('Fixture write failure')
        ):
            event = self.exchange(RenameProfileCommand('old-default', 'new-default'))
        self.assertFalse(event.success)
        self.assertEqual(
            event.operation_type, ProfileOperationCode.RENAMED_DEFAULT_UNCONFIRMED
        )
        self.assertEqual(
            event.params,
            {'old_profile': 'old-default', 'new_profile': 'new-default'},
        )
        self.assertFalse(ProfileManager('old-default').exists())
        self.assertTrue(ProfileManager('new-default').exists())


if __name__ == '__main__':
    unittest.main()
