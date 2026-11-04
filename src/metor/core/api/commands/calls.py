"""Commands for explicitly consented calls and bounded real-time audio."""

from dataclasses import dataclass, field

from metor.shared import Constants

# Local Package Imports
from metor.core.api.base import IpcCommand
from metor.core.api.codes import CommandType
from metor.core.api.registry import register_command


@register_command(CommandType.START_CALL)
@dataclass
class StartCallCommand(IpcCommand):
    """Requests phone consent from a target under a fresh caller-chosen identity.

    Core establishes a call-only transport or borrows an accepted LIVE transport;
    this command does not grant LIVE chat access or start local microphone input.
    Admission returns CallStateEvent or a typed CallRejectedEvent.
    """

    target: str = ''
    call_id: str = ''
    command_type: CommandType = field(default=CommandType.START_CALL, init=False)


@register_command(CommandType.ACCEPT_CALL)
@dataclass
class AcceptCallCommand(IpcCommand):
    """Accepts the current incoming Core identity for this exact IPC client.

    Acceptance grants Call audio only. Restricted clients additionally require
    the protected locked-call preference; no message or general LIVE grant follows.
    """

    call_id: str = ''
    command_type: CommandType = field(default=CommandType.ACCEPT_CALL, init=False)


@register_command(CommandType.REJECT_CALL)
@dataclass
class RejectCallCommand(IpcCommand):
    """Declines an incoming Call without ending an independently accepted LIVE chat."""

    call_id: str = ''
    command_type: CommandType = field(default=CommandType.REJECT_CALL, init=False)


@register_command(CommandType.CANCEL_CALL)
@dataclass
class CancelCallCommand(IpcCommand):
    """Withdraws an exact owned request, including acceptance that raced cancellation."""

    call_id: str = ''
    command_type: CommandType = field(default=CommandType.CANCEL_CALL, init=False)


@register_command(CommandType.HANGUP_CALL)
@dataclass
class HangupCallCommand(IpcCommand):
    """Ends this client's accepted Call and releases audio and Call-only transport."""

    call_id: str = ''
    command_type: CommandType = field(default=CommandType.HANGUP_CALL, init=False)


@register_command(CommandType.MUTE_CALL)
@dataclass
class MuteCallCommand(IpcCommand):
    """Changes microphone admission for an owned active Call, preserving receive audio."""

    call_id: str = ''
    muted: bool = False
    command_type: CommandType = field(default=CommandType.MUTE_CALL, init=False)


@register_command(CommandType.GET_CALLS)
@dataclass
class GetCallsCommand(IpcCommand):
    """Reads bounded, privacy-filtered Call metadata without granting or consuming audio."""

    command_type: CommandType = field(default=CommandType.GET_CALLS, init=False)


@register_command(CommandType.SEND_CALL_AUDIO)
@dataclass
class SendCallAudioCommand(IpcCommand):
    """Admits one base64 PCM frame and its monotonic sequence for an owned active Call.

    The frame must match the shared codec and bounds. Admission does not guarantee
    playback: expired queued frames are discarded, never recorded or sent as DROP.
    """

    call_id: str = ''
    sequence: int = 0
    data: str = ''
    command_type: CommandType = field(default=CommandType.SEND_CALL_AUDIO, init=False)


@register_command(CommandType.READ_CALL_AUDIO)
@dataclass
class ReadCallAudioCommand(IpcCommand):
    """Consumes up to max_frames fresh received frames for this Call's exact owner.

    Core returns bounded ephemeral audio and discards expired frames. This command
    has no message receipt, history, retention or Voice-consume side effect.
    """

    call_id: str = ''
    max_frames: int = Constants.CALL_AUDIO_READ_FRAMES
    command_type: CommandType = field(default=CommandType.READ_CALL_AUDIO, init=False)
