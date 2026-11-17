"""Revision-qualified protected GUI preference commands."""

from dataclasses import dataclass, field

# Local Package Imports
from ..base import IpcCommand
from ..codes import CommandType
from ..preferences import GuiPreferences
from ..registry import register_command


@register_command(CommandType.GET_GUI_PREFERENCES)
@dataclass
class GetGuiPreferencesCommand(IpcCommand):
    """Requests protected GUI preferences for the authenticated profile."""

    command_type: CommandType = field(
        default=CommandType.GET_GUI_PREFERENCES, init=False
    )


@register_command(CommandType.SET_GUI_PREFERENCES)
@dataclass
class SetGuiPreferencesCommand(IpcCommand):
    """Requests an atomic update; root security policy needs password strength."""

    expected_revision: int = 0
    preferences: GuiPreferences = field(default_factory=GuiPreferences)
    command_type: CommandType = field(
        default=CommandType.SET_GUI_PREFERENCES, init=False
    )

    def __post_init__(self) -> None:
        """Rejects invalid direct callers as well as invalid decoded DTOs.

        Args:
            None
        Returns:
            None
        """
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise ValueError('Invalid GUI preference revision')
        if not isinstance(self.preferences, GuiPreferences):
            raise ValueError('Invalid GUI preference document')
        self.preferences.__post_init__()
