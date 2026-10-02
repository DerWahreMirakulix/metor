"""Present telephone signaling without granting unavailable Terminal media access."""

from __future__ import annotations

from typing import TYPE_CHECKING

from metor.core.api import (
    CallAudioEvent,
    CallAudioSentEvent,
    CallInfo,
    CallRejectedEvent,
    CallsStateEvent,
    CallState,
    CallStateEvent,
    CancelCallCommand,
    GetCallsCommand,
    HangupCallCommand,
    IpcEvent,
    MuteCallCommand,
    RejectCallCommand,
)
from metor.shared import escape_terminal_text
from metor.ui.terminal import Help
from metor.ui.terminal.models import StatusTone

# Local Package Imports
from metor.ui.terminal.chat.ipc import IpcClient
from metor.ui.terminal.chat.models import ChatMessageType
from metor.ui.terminal.chat.renderer import ChatRenderer

if TYPE_CHECKING:
    from metor.ui.terminal.chat.event.protocols import EventHandlerProtocol


MEDIA_UNAVAILABLE: str = (
    'Telephone calls require a local duplex audio adapter. '
    'Terminal cannot start or accept call audio; use a capable frontend. '
    'Live-chat acceptance grants messages only.'
)


def _status(renderer: ChatRenderer, text: str) -> None:
    """Render a signaling or capability result without changing chat focus."""
    renderer.print_message(
        text, msg_type=ChatMessageType.STATUS, tone=StatusTone.SYSTEM
    )


def dispatch_call_command(
    parts: list[str], ipc: IpcClient, renderer: ChatRenderer
) -> bool:
    """Dispatch exact call identities through typed Core authorization.

    Terminal ships without an audio adapter. Starting or accepting a call is
    refused before IPC so acceptance cannot create a silent, unusable call.
    Other controls retain Core's exact identity and client ownership checks.

    Args:
        parts: Tokenized explicit command, preserving the case of opaque IDs.
        ipc: Public authenticated SDK connection.
        renderer: Terminal presentation owner.

    Returns:
        Whether this is a Terminal call command, including invalid usage.
    """
    if parts[0] == '/calls':
        if len(parts) == 1:
            ipc.send_command(GetCallsCommand())
        else:
            _status(renderer, Help.show_command_help('/calls').strip())
        return True
    if parts[0] != '/call':
        return False
    if len(parts) != 3:
        _status(renderer, Help.show_command_help('/call').strip())
        return True
    operation, call_id = parts[1:]
    if operation in ('start', 'accept'):
        _status(renderer, MEDIA_UNAVAILABLE)
    elif operation == 'reject':
        ipc.send_command(RejectCallCommand(call_id=call_id))
    elif operation == 'cancel':
        ipc.send_command(CancelCallCommand(call_id=call_id))
    elif operation == 'hangup':
        ipc.send_command(HangupCallCommand(call_id=call_id))
    elif operation in ('mute', 'unmute'):
        ipc.send_command(MuteCallCommand(call_id=call_id, muted=operation == 'mute'))
    else:
        _status(renderer, Help.show_command_help('/call').strip())
    return True


def _show_call(handler: EventHandlerProtocol, call: CallInfo) -> None:
    """Render one typed call state without selecting or consuming a chat."""
    identity = escape_terminal_text(call.call_id)
    state = call.state.value.replace('_', ' ')
    text = f'Call {identity}: {state}'
    if call.muted:
        text += ', microphone muted'
    if call.reason is not None:
        text += f' ({call.reason.value.replace("_", " ")})'
    if call.state is CallState.INCOMING:
        text += (
            f'. Reject with /call reject {identity}. '
            'Accept in a frontend with a local duplex audio adapter.'
        )
    elif call.state is CallState.ACTIVE and not call.owned:
        text += '. Media belongs to another client.'
    if call.alias:
        handler._remember_peer(call.alias, call.peer)
        handler._print_peer_status(
            '{alias}: ' + text, StatusTone.INFO, call.alias, call.peer
        )
    else:
        _status(handler._renderer, text)


def handle_call_event(handler: EventHandlerProtocol, event: IpcEvent) -> bool:
    """Handle telephone metadata separately from LIVE chat and message Voice.

    Call media is never requested or played in Terminal. Receipt of an
    unsolicited bounded media event does not grant a playback capability.
    """
    if isinstance(event, CallStateEvent):
        _show_call(handler, event.call)
        return True
    if isinstance(event, CallsStateEvent):
        if not event.calls:
            _status(handler._renderer, 'No telephone calls.')
        for call in event.calls:
            _show_call(handler, call)
        return True
    if isinstance(event, CallRejectedEvent):
        _status(
            handler._renderer,
            f'Call {escape_terminal_text(event.call_id)} action rejected: '
            f'{event.reason.value.replace("_", " ")}.',
        )
        return True
    return isinstance(event, (CallAudioEvent, CallAudioSentEvent))
