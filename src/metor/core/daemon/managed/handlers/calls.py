"""Typed call command adapter; consent and media authorization stay in Core."""

import socket
from typing import Callable

from metor.core.api import (
    AcceptCallCommand,
    CallInfo,
    CallReason,
    CallRejectedEvent,
    CallStateEvent,
    CallsStateEvent,
    CancelCallCommand,
    GetCallsCommand,
    HangupCallCommand,
    IpcCommand,
    IpcEvent,
    MuteCallCommand,
    NotificationPrivacy,
    ReadCallAudioCommand,
    RejectCallCommand,
    SendCallAudioCommand,
    StartCallCommand,
)
from metor.core.daemon.managed.network.calls import CallController

CALL_COMMANDS = (
    StartCallCommand,
    AcceptCallCommand,
    RejectCallCommand,
    CancelCallCommand,
    HangupCallCommand,
    MuteCallCommand,
    GetCallsCommand,
    SendCallAudioCommand,
    ReadCallAudioCommand,
)


class CallCommandHandler:
    """Routes call controls through their exact identity and frontend owner."""

    def __init__(
        self,
        calls: CallController,
        privacy: Callable[[socket.socket], NotificationPrivacy],
    ) -> None:
        """Installs the independent call owner and local lockscreen privacy projection."""
        self.calls = calls
        self.privacy = privacy

    def handle(self, cmd: IpcCommand, client: socket.socket) -> IpcEvent:
        """Executes one session-authorized command and masks all direct state outcomes."""
        result: IpcEvent
        if isinstance(cmd, StartCallCommand):
            result = self.calls.start(cmd.target, cmd.call_id, client)
        elif isinstance(cmd, AcceptCallCommand):
            result = self.calls.accept(cmd.call_id, client)
        elif isinstance(cmd, RejectCallCommand):
            result = self.calls.control(cmd.call_id, client, CallReason.REJECTED)
        elif isinstance(cmd, CancelCallCommand):
            result = self.calls.control(cmd.call_id, client, CallReason.CANCELLED)
        elif isinstance(cmd, HangupCallCommand):
            result = self.calls.control(cmd.call_id, client, CallReason.HUNG_UP)
        elif isinstance(cmd, MuteCallCommand):
            result = self.calls.mute(cmd.call_id, client, cmd.muted)
        elif isinstance(cmd, GetCallsCommand):
            result = CallsStateEvent(
                calls=self.calls.list_for_client(client, self.privacy(client))
            )
        elif isinstance(cmd, SendCallAudioCommand):
            result = self.calls.send_audio(cmd.call_id, client, cmd.sequence, cmd.data)
        elif isinstance(cmd, ReadCallAudioCommand):
            result = self.calls.read_audio(cmd.call_id, client, cmd.max_frames)
        else:
            result = CallRejectedEvent(reason=CallReason.INVALID_STATE)
        if isinstance(result, CallStateEvent):
            result = self.calls.project_event(
                client, result, self.privacy(client)
            ) or CallStateEvent(call=CallInfo(call_id=result.call.call_id))
        return result
