"""Headless-safe routing for local profile lifecycle operations."""

from metor.core.api import (
    AddProfileCommand,
    EventType,
    IpcCommand,
    IpcEvent,
    MigrateProfileSecurityCommand,
    RemoveProfileCommand,
    RenameProfileCommand,
    SetDefaultProfileCommand,
    create_event,
)
from metor.core.api.codes import ProfileOperationCode
from metor.core.api.events import ProfileOperationResultEvent
from metor.data.profile import (
    ProfileManager,
    ProfileOperationResult,
    ProfileSecurityMode,
)


class ProfileCommandHandler:
    """Routes local profile-management IPC commands to profile lifecycle operations."""

    @staticmethod
    def _build_result_event(
        result: ProfileOperationResult,
    ) -> ProfileOperationResultEvent:
        """
        Converts one local profile operation result into a strict IPC event.

        Args:
            result (ProfileOperationResult): The local profile operation outcome.

        Returns:
            ProfileOperationResultEvent: The typed profile-operation result event.
        """
        return ProfileOperationResultEvent(
            success=result.success,
            operation_type=ProfileOperationCode(result.operation_type.value),
            params=dict(result.params),
        )

    def handle(self, cmd: IpcCommand) -> IpcEvent:
        """
        Routes one local profile-management command.

        Args:
            cmd (IpcCommand): The parsed IPC command DTO.

        Returns:
            IpcEvent: The typed result event or UNKNOWN_COMMAND.
        """
        if isinstance(cmd, AddProfileCommand):
            result = ProfileManager.add_profile_folder(
                cmd.name,
                is_remote=cmd.is_remote,
                port=cmd.port,
                security_mode=ProfileSecurityMode(cmd.security_mode),
            )
            return self._build_result_event(result)

        if isinstance(cmd, MigrateProfileSecurityCommand):
            result = ProfileManager.migrate_profile_security(
                cmd.name,
                ProfileSecurityMode(cmd.target_mode),
                current_password=cmd.current_password,
                new_password=cmd.new_password,
            )
            return self._build_result_event(result)

        if isinstance(cmd, RemoveProfileCommand):
            result = ProfileManager.remove_profile_folder(
                cmd.name,
                active_profile=cmd.active_profile,
            )
            return self._build_result_event(result)

        if isinstance(cmd, RenameProfileCommand):
            result = ProfileManager.rename_profile_folder(cmd.old_name, cmd.new_name)
            return self._build_result_event(result)

        if isinstance(cmd, SetDefaultProfileCommand):
            result = ProfileManager.set_default_profile(cmd.profile_name)
            return self._build_result_event(result)

        return create_event(EventType.UNKNOWN_COMMAND)
