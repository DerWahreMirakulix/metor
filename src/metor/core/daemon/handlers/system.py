"""
Module defining the SystemCommandHandler.
Encapsulates profile-level system operations such as Tor address generation.
"""

from metor.core import TorManager
from metor.core.api import (
    IpcCommand,
    IpcEvent,
    TransCode,
    GetAddressCommand,
    GenerateAddressCommand,
    AddressDataEvent,
    ActionErrorEvent,
)
from metor.data.profile import ProfileManager


class SystemCommandHandler:
    """Processes stateless system commands mapping directly to Tor or Profile states."""

    def __init__(self, pm: ProfileManager, tm: TorManager) -> None:
        """
        Initializes the SystemCommandHandler.

        Args:
            pm (ProfileManager): Profile configuration.
            tm (TorManager): Tor network manager.

        Returns:
            None
        """
        self._pm: ProfileManager = pm
        self._tm: TorManager = tm

    def handle(self, cmd: IpcCommand) -> IpcEvent:
        """
        Routes the system command to the TorManager and generates a DTO response.

        Args:
            cmd (IpcCommand): The system-related IPC command.

        Returns:
            IpcEvent: The strictly typed response event (Success or Error DTO).
        """
        if isinstance(cmd, GetAddressCommand):
            success, code, params = self._tm.get_address()
            if success:
                return AddressDataEvent(
                    action=cmd.action,
                    code=code,
                    profile=str(params['profile']),
                    onion=str(params['onion']),
                )
            return ActionErrorEvent(
                action=cmd.action,
                code=code,
                target=str(params.get('profile', '')),
            )

        if isinstance(cmd, GenerateAddressCommand):
            success, code, params = self._tm.generate_address()
            if success:
                return AddressDataEvent(
                    action=cmd.action,
                    code=code,
                    profile=str(params['profile']),
                    onion=str(params['onion']),
                )
            return ActionErrorEvent(
                action=cmd.action,
                code=code,
                target=str(params.get('profile', '')),
            )

        return ActionErrorEvent(
            action=cmd.action,
            code=TransCode.UNKNOWN_COMMAND,
        )
