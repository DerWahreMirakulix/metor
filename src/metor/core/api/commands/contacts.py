"""Contact-management command DTOs."""

from dataclasses import dataclass, field
from typing import Optional

# Local Package Imports
from metor.core.api.base import IpcCommand
from metor.core.api.codes import CommandType
from metor.core.api.registry import register_command


@register_command(CommandType.GET_CONTACTS_LIST)
@dataclass
class GetContactsListCommand(IpcCommand):
    """Requests the structured address book."""

    chat_mode: bool = False
    command_type: CommandType = field(
        default=CommandType.GET_CONTACTS_LIST,
        init=False,
    )


@register_command(CommandType.ADD_CONTACT)
@dataclass
class AddContactCommand(IpcCommand):
    """Adds a new contact or promotes a discovered peer."""

    alias: str
    onion: Optional[str] = None
    command_type: CommandType = field(default=CommandType.ADD_CONTACT, init=False)


@register_command(CommandType.REMOVE_CONTACT)
@dataclass
class RemoveContactCommand(IpcCommand):
    """Removes a saved contact or discovered peer."""

    alias: str
    command_type: CommandType = field(
        default=CommandType.REMOVE_CONTACT,
        init=False,
    )


@register_command(CommandType.RENAME_CONTACT)
@dataclass
class RenameContactCommand(IpcCommand):
    """Renames an existing contact or discovered peer."""

    old_alias: str
    new_alias: str
    command_type: CommandType = field(
        default=CommandType.RENAME_CONTACT,
        init=False,
    )


@register_command(CommandType.CLEAR_CONTACTS)
@dataclass
class ClearContactsCommand(IpcCommand):
    """Clears the complete address book."""

    command_type: CommandType = field(
        default=CommandType.CLEAR_CONTACTS,
        init=False,
    )
