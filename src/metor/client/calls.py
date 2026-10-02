"""SDK mixin for exact call controls and ephemeral bidirectional PCM frames."""

import secrets
from typing import Protocol, Type, TypeVar, cast

from metor.core.api import (
    AcceptCallCommand,
    CallAudioEvent,
    CallAudioSentEvent,
    CallRejectedEvent,
    CallStateEvent,
    CallsStateEvent,
    CancelCallCommand,
    GetCallsCommand,
    HangupCallCommand,
    IpcCommand,
    IpcEvent,
    MuteCallCommand,
    ReadCallAudioCommand,
    RejectCallCommand,
    SendCallAudioCommand,
    StartCallCommand,
)
from metor.shared.constants import Constants

T = TypeVar('T', bound=IpcEvent)
CallOutcome = CallStateEvent | CallRejectedEvent


class CallRequester(Protocol):
    """The reference client's typed correlated request boundary."""

    def request(
        self,
        cmd: IpcCommand,
        expected: Type[T],
    ) -> T | None:
        """Requests one typed daemon outcome."""
        ...

    def _request_types(
        self, cmd: IpcCommand, expected_types: tuple[type[IpcEvent], ...]
    ) -> IpcEvent | None:
        """Requests a bounded set of typed terminal outcomes."""
        ...


class CallClientMixin:
    """Offers call controls; local adapters own explicit microphone and output access."""

    def start_call(
        self: CallRequester, target: str, call_id: str | None = None
    ) -> CallOutcome | None:
        """Starts a call without granting or changing LIVE chat authorization."""
        return cast(
            CallOutcome | None,
            self._request_types(
                StartCallCommand(
                    target=target,
                    call_id=call_id or secrets.token_hex(Constants.CALL_ID_BYTES),
                ),
                (CallStateEvent, CallRejectedEvent),
            ),
        )

    def accept_call(self: CallRequester, call_id: str) -> CallOutcome | None:
        """Explicitly accepts exactly one pending call for this IPC client."""
        return cast(
            CallOutcome | None,
            self._request_types(
                AcceptCallCommand(call_id=call_id), (CallStateEvent, CallRejectedEvent)
            ),
        )

    def reject_call(self: CallRequester, call_id: str) -> CallOutcome | None:
        """Rejects the current incoming identity without affecting its chat."""
        return cast(
            CallOutcome | None,
            self._request_types(
                RejectCallCommand(call_id=call_id), (CallStateEvent, CallRejectedEvent)
            ),
        )

    def cancel_call(self: CallRequester, call_id: str) -> CallOutcome | None:
        """Withdraws this client's request, hanging up if peer acceptance raced cancellation."""
        return cast(
            CallOutcome | None,
            self._request_types(
                CancelCallCommand(call_id=call_id), (CallStateEvent, CallRejectedEvent)
            ),
        )

    def hangup_call(self: CallRequester, call_id: str) -> CallOutcome | None:
        """Ends only this client's accepted call and releases its media buffers."""
        return cast(
            CallOutcome | None,
            self._request_types(
                HangupCallCommand(call_id=call_id), (CallStateEvent, CallRejectedEvent)
            ),
        )

    def mute_call(self: CallRequester, call_id: str, muted: bool) -> CallOutcome | None:
        """Changes capture admission; mute survives application restriction."""
        return cast(
            CallOutcome | None,
            self._request_types(
                MuteCallCommand(call_id=call_id, muted=muted),
                (CallStateEvent, CallRejectedEvent),
            ),
        )

    def get_calls(self: CallRequester) -> CallsStateEvent | None:
        """Returns a content-free privacy-filtered current call snapshot."""
        return cast(
            CallsStateEvent | None,
            self._request_types(GetCallsCommand(), (CallsStateEvent,)),
        )

    def send_call_audio(
        self: CallRequester, call_id: str, sequence: int, data: str
    ) -> CallAudioSentEvent | CallRejectedEvent | None:
        """Enqueues one bounded PCM frame, never records or retries conversation audio."""
        return cast(
            CallAudioSentEvent | CallRejectedEvent | None,
            self._request_types(
                SendCallAudioCommand(call_id=call_id, sequence=sequence, data=data),
                (CallAudioSentEvent, CallRejectedEvent),
            ),
        )

    def read_call_audio(
        self: CallRequester,
        call_id: str,
        max_frames: int = Constants.CALL_AUDIO_READ_FRAMES,
    ) -> CallAudioEvent | CallRejectedEvent | None:
        """Consumes fresh bounded received frames for the exact accepted owner."""
        return cast(
            CallAudioEvent | CallRejectedEvent | None,
            self._request_types(
                ReadCallAudioCommand(call_id=call_id, max_frames=max_frames),
                (CallAudioEvent, CallRejectedEvent),
            ),
        )
