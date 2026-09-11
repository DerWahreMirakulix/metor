"""Messaging command DTOs for live, inbox, and stored-message flows."""

from dataclasses import dataclass, field
from typing import List, Optional

# Local Package Imports
from metor.core.api.base import IpcCommand
from metor.core.api.codes import CommandType, MessageDirectionCode
from metor.core.api.content import Delivery, MessageContent
from metor.core.api.registry import register_command


@register_command(CommandType.SEND_MESSAGE)
@dataclass
class SendMessageCommand(IpcCommand):
    """Sends typed content using the requested delivery semantics."""

    target: str
    delivery: Delivery
    content: MessageContent
    msg_id: str
    command_type: CommandType = field(default=CommandType.SEND_MESSAGE, init=False)


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
    delivery: Optional[Delivery] = None
    command_type: CommandType = field(default=CommandType.MARK_READ, init=False)


@register_command(CommandType.FALLBACK)
@dataclass
class FallbackCommand(IpcCommand):
    """Forces pending live messages into the drop queue."""

    target: str
    msg_ids: Optional[List[str]] = None
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
    """Clears only local DROP conversation payload/history state."""

    target: Optional[str] = None
    non_contacts_only: bool = False
    command_type: CommandType = field(
        default=CommandType.CLEAR_MESSAGES,
        init=False,
    )


@register_command(CommandType.DELETE_MESSAGE)
@dataclass
class DeleteMessageCommand(IpcCommand):
    """Deletes one eligible local DROP payload while retaining dedupe metadata."""

    target: str
    msg_id: str
    direction: Optional[MessageDirectionCode] = None
    command_type: CommandType = field(default=CommandType.DELETE_MESSAGE, init=False)


@register_command(CommandType.DISMISS_LIVE_CONTEXT)
@dataclass
class DismissLiveContextCommand(IpcCommand):
    """Destroys resolved inbound state for a disconnected LIVE context."""

    target: str
    command_type: CommandType = field(
        default=CommandType.DISMISS_LIVE_CONTEXT,
        init=False,
    )


@register_command(CommandType.BEGIN_VOICE)
@dataclass
class BeginVoiceCommand(IpcCommand):
    """Begins one peer-bound logical Voice turn."""

    target: str
    delivery: Delivery
    msg_id: str
    codec: str
    command_type: CommandType = field(default=CommandType.BEGIN_VOICE, init=False)


@register_command(CommandType.APPEND_VOICE_CHUNK)
@dataclass
class AppendVoiceChunkCommand(IpcCommand):
    """Appends one bounded Base64 Voice chunk at an exact byte offset."""

    msg_id: str
    offset: int
    data: str
    command_type: CommandType = field(
        default=CommandType.APPEND_VOICE_CHUNK,
        init=False,
    )


@register_command(CommandType.FINALIZE_VOICE)
@dataclass
class FinalizeVoiceCommand(IpcCommand):
    """Finalizes the current logical Voice turn without changing its target."""

    msg_id: str
    duration_ms: Optional[int] = None
    command_type: CommandType = field(
        default=CommandType.FINALIZE_VOICE,
        init=False,
    )


@register_command(CommandType.GET_VOICE_CHUNK)
@dataclass
class GetVoiceChunkCommand(IpcCommand):
    """Reads one authenticated bounded range from retained Voice content."""

    target: str
    msg_id: str
    direction: MessageDirectionCode
    offset: int
    max_bytes: int
    command_type: CommandType = field(
        default=CommandType.GET_VOICE_CHUNK,
        init=False,
    )


@register_command(CommandType.RELEASE_VOICE)
@dataclass
class ReleaseVoiceCommand(IpcCommand):
    """Consumes one finalized inbound Voice item after client handoff."""

    target: str
    msg_id: str
    command_type: CommandType = field(default=CommandType.RELEASE_VOICE, init=False)


@register_command(CommandType.COMMIT_VOICE)
@dataclass
class CommitVoiceCommand(IpcCommand):
    """Commits one finalized DROP Voice draft to pending delivery."""

    target: str
    msg_id: str
    command_type: CommandType = field(default=CommandType.COMMIT_VOICE, init=False)


@register_command(CommandType.CANCEL_VOICE)
@dataclass
class CancelVoiceCommand(IpcCommand):
    """Cancels one unsent DROP Voice draft."""

    target: str
    msg_id: str
    command_type: CommandType = field(default=CommandType.CANCEL_VOICE, init=False)
