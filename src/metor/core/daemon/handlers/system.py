"""
Module defining the SystemCommandHandler.
Encapsulates profile-level system operations such as Tor address generation.
"""

from metor.core import TorManager
from metor.core.api import (
    IpcCommand,
    CommandResponseEvent,
    TransCode,
    GetAddressCommand,
    GenerateAddressCommand,
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

    def handle(self, cmd: IpcCommand) -> CommandResponseEvent:
        """
        Routes the system command to the TorManager.

        Args:
            cmd (IpcCommand): The system-related IPC command.

        Returns:
            CommandResponseEvent: The strictly typed response event.
        """
        if isinstance(cmd, GetAddressCommand):
            _, msg = self._tm.get_address()
            return CommandResponseEvent(
                action=cmd.action, code=TransCode.GENERIC_MSG, params={'msg': msg}
            )

        if isinstance(cmd, GenerateAddressCommand):
            _, msg = self._tm.generate_address()
            return CommandResponseEvent(
                action=cmd.action, code=TransCode.GENERIC_MSG, params={'msg': msg}
            )

        return CommandResponseEvent(
            action=cmd.action,
            success=False,
            code=TransCode.GENERIC_MSG,
            params={'msg': 'Unknown command.'},
        )
