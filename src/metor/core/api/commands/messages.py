"""Messaging command DTOs for live, inbox, and stored-message flows."""

from dataclasses import dataclass, field
from typing import Optional

# Local Package Imports
from metor.core.api.base import IpcCommand
from metor.core.api.codes import CommandType
from metor.core.api.registry import register_command


@register_command(CommandType.MSG)
@dataclass
class MsgCommand(IpcCommand):
    """Sends a live chat message to a peer."""

    target: str
    text: str
    msg_id: str
    command_type: CommandType = field(default=CommandType.MSG, init=False)


@register_command(CommandType.SEND_DROP)
@dataclass
class SendDropCommand(IpcCommand):
    """Queues an asynchronous offline message."""

    target: str
    text: str
    msg_id: str
    command_type: CommandType = field(default=CommandType.SEND_DROP, init=False)


@register_command(CommandType.GET_INBOX)
@dataclass
class GetInboxCommand(IpcCommand):
    """Requests unread-message counters."""

    command_type: CommandType = field(default=CommandType.GET_INBOX, init=False)


@register_command(CommandType.MARK_READ)
@dataclass
class MarkReadCommand(IpcCommand):
    """Reads and clears unread messages for a peer."""

    target: str
    command_type: CommandType = field(default=CommandType.MARK_READ, init=False)


@register_command(CommandType.FALLBACK)
@dataclass
class FallbackCommand(IpcCommand):
    """Forces pending live messages into the drop queue."""

    target: str
    command_type: CommandType = field(default=CommandType.FALLBACK, init=False)


@register_command(CommandType.GET_MESSAGES)
@dataclass
class GetMessagesCommand(IpcCommand):
    """Requests stored message history."""

    target: Optional[str] = None
    limit: Optional[int] = None
    command_type: CommandType = field(default=CommandType.GET_MESSAGES, init=False)


@register_command(CommandType.CLEAR_MESSAGES)
@dataclass
class ClearMessagesCommand(IpcCommand):
    """Clears stored message history."""

    target: Optional[str] = None
    non_contacts_only: bool = False
    command_type: CommandType = field(
        default=CommandType.CLEAR_MESSAGES,
        init=False,
    )
