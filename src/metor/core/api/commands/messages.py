"""Messaging command DTOs for live, inbox, and stored-message flows."""

from dataclasses import dataclass, field
from typing import List, Optional

# Local Package Imports
from metor.core.api.base import IpcCommand
from metor.core.api.codes import CommandType, MessageDirectionCode
from metor.core.api.content import Delivery, MessageContent
from metor.core.api.registry import register_command
from metor.core.api.content import is_valid_message_id
from metor.shared.constants import Constants


@register_command(CommandType.SEND_MESSAGE)
@dataclass
class SendMessageCommand(IpcCommand):
    """Sends typed content using the requested delivery semantics."""

    target: str
    delivery: Delivery
    content: MessageContent
    msg_id: str
    local_acceptance: bool = False
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
    max_messages: Optional[int] = None
    max_payload_bytes: Optional[int] = None
    command_type: CommandType = field(default=CommandType.MARK_READ, init=False)

    def __post_init__(self) -> None:
        """Validates optional bounded foreground handoff without changing legacy callers.

        Args:
            None
        Returns:
            None
        """
        for value, maximum in (
            (self.max_messages, Constants.MAX_RETAINED_PAGE_SIZE),
            (self.max_payload_bytes, Constants.TEXT_HANDOFF_MAX_BYTES),
        ):
            if value is not None and (
                type(value) is not int or not 0 < value <= maximum
            ):
                raise ValueError('Invalid text handoff bound')


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
    before_msg_id: Optional[str] = None
    before_direction: Optional[MessageDirectionCode] = None
    max_payload_bytes: Optional[int] = None
    command_type: CommandType = field(default=CommandType.GET_MESSAGES, init=False)

    def __post_init__(self) -> None:
        """Validates opt-in archive paging while preserving legacy requests.

        Args:
            None
        Returns:
            None
        """
        if (self.before_msg_id is None) != (self.before_direction is None):
            raise ValueError('Archive boundary requires both identity and direction')
        if self.before_msg_id is not None and self.max_payload_bytes is None:
            raise ValueError('Archive continuation requires bounded paging')
        if self.before_msg_id is not None and not is_valid_message_id(
            self.before_msg_id
        ):
            raise ValueError('Invalid archive boundary identity')
        if self.max_payload_bytes is not None and (
            type(self.max_payload_bytes) is not int
            or not 0 < self.max_payload_bytes <= Constants.ARCHIVE_PAGE_MAX_BYTES
            or type(self.limit) is not int
            or not 0 < self.limit <= Constants.MAX_RETAINED_PAGE_SIZE
        ):
            raise ValueError('Invalid archive page bounds')


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
    owner_token: Optional[str] = None
    context_generation: Optional[int] = None
    command_type: CommandType = field(default=CommandType.BEGIN_VOICE, init=False)

    def __post_init__(self) -> None:
        """Rejects booleans and invalid context-generation assertions.

        Args:
            None
        Returns:
            None
        """
        if self.context_generation is not None and (
            type(self.context_generation) is not int or self.context_generation <= 0
        ):
            raise ValueError('Invalid LIVE context generation')


@register_command(CommandType.APPEND_VOICE_CHUNK)
@dataclass
class AppendVoiceChunkCommand(IpcCommand):
    """Appends one bounded Base64 Voice chunk at an exact byte offset."""

    msg_id: str
    offset: int
    data: str
    owner_token: Optional[str] = None
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
    owner_token: Optional[str] = None
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
    owner_token: Optional[str] = None
    command_type: CommandType = field(
        default=CommandType.GET_VOICE_CHUNK,
        init=False,
    )


@register_command(CommandType.LIST_RETAINED_MESSAGES)
@dataclass
class ListRetainedMessagesCommand(IpcCommand):
    """Enumerates retained message identities without reading or consuming content."""

    target: Optional[str] = None
    delivery: Optional[Delivery] = None
    direction: Optional[MessageDirectionCode] = None
    cursor: Optional[str] = None
    limit: int = Constants.DEFAULT_RETAINED_PAGE_SIZE
    owner_token: Optional[str] = None
    msg_id: Optional[str] = None
    command_type: CommandType = field(
        default=CommandType.LIST_RETAINED_MESSAGES,
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
    owner_token: Optional[str] = None
    command_type: CommandType = field(default=CommandType.COMMIT_VOICE, init=False)


@register_command(CommandType.CANCEL_VOICE)
@dataclass
class CancelVoiceCommand(IpcCommand):
    """Cancels one unsent DROP Voice draft."""

    target: str
    msg_id: str
    owner_token: Optional[str] = None
    command_type: CommandType = field(default=CommandType.CANCEL_VOICE, init=False)


@register_command(CommandType.GET_MESSAGE_OUTCOME)
@dataclass
class GetMessageOutcomeCommand(IpcCommand):
    """Queries one stable receipt without reading or consuming message content."""

    onion: str = ''
    msg_id: str = ''
    direction: MessageDirectionCode = MessageDirectionCode.OUT
    command_type: CommandType = field(
        default=CommandType.GET_MESSAGE_OUTCOME, init=False
    )
