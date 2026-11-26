"""Owns exact call consent and its lifecycle independently of LIVE chat."""

import socket
import threading
import time
from dataclasses import replace
from typing import Callable
from weakref import WeakKeyDictionary, WeakSet

from metor.core.api import (
    CallInfo,
    CallReason,
    CallState,
    CallStateEvent,
    CallRejectedEvent,
    CallAudioEvent,
    CallAudioSentEvent,
    IpcCommand,
    IpcEvent,
    CancelCallCommand,
    HangupCallCommand,
    MuteCallCommand,
    ReadCallAudioCommand,
    SendCallAudioCommand,
    NotificationPrivacy,
    is_valid_message_id,
)
from metor.core.daemon.managed.models import TorCommand
from metor.core.daemon.managed.crypto import Crypto
from metor.core.tor import TorManager
from metor.data import ContactManager
from metor.shared.constants import Constants

# Local Package Imports
from ..state import StateTracker
from ..stream import TcpStreamReader
from .models import CallSession
from . import media, signaling, transport


class CallController:
    """Serializes call state; physical network I/O occurs outside its ownership lock."""

    def __init__(
        self,
        tm: TorManager,
        cm: ContactManager,
        crypto: Crypto,
        state: StateTracker,
        broadcast: Callable[[IpcEvent], None],
        stop_flag: threading.Event,
        chat_end: Callable[[str, socket.socket], None] | None = None,
    ) -> None:
        """Creates a bounded ephemeral owner and its timeout/heartbeat monitor."""
        self.tm = tm
        self.cm = cm
        self.crypto = crypto
        self.transport_state = state
        self.broadcast = broadcast
        self.stop_flag = stop_flag
        self.chat_end = chat_end
        self.lock = threading.RLock()
        self.sessions: dict[str, CallSession] = {}
        self.exclusive_sockets: WeakSet[socket.socket] = WeakSet()
        self.local_ids: WeakKeyDictionary[socket.socket, set[str]] = WeakKeyDictionary()
        self.offered_ids: WeakKeyDictionary[socket.socket, set[str]] = (
            WeakKeyDictionary()
        )
        self.closed = threading.Event()
        self.monitor = threading.Thread(
            target=transport.monitor, args=(self,), daemon=True
        )
        self.monitor.start()

    def _project(self, session: CallSession, client: socket.socket | None) -> CallInfo:
        """Returns a copy, binding ownership to the requesting local connection."""
        return replace(
            session.info, owned=client is not None and session.owner is client
        )

    def _emit(self, session: CallSession) -> None:
        """Broadcasts only content-free state; local access applies privacy projection."""
        with self.lock:
            event = CallStateEvent(call=self._project(session, None))
        self.broadcast(event)

    def list_for_client(
        self,
        client: socket.socket,
        privacy: NotificationPrivacy = NotificationPrivacy.SHOW_ALL,
    ) -> list[CallInfo]:
        """Projects call metadata without granting media access or revealing masked peers."""
        with self.lock:
            result: list[CallInfo] = []
            for session in self.sessions.values():
                if privacy is NotificationPrivacy.OFF and session.owner is not client:
                    continue
                info = self._project(session, client)
                if privacy is not NotificationPrivacy.SHOW_ALL:
                    info.peer = ''
                    info.alias = ''
                result.append(info)
            return result

    def project_event(
        self, client: socket.socket, event: CallStateEvent, privacy: NotificationPrivacy
    ) -> CallStateEvent | None:
        """Projects lifecycle events for one client while retaining its terminal signal."""
        with self.lock:
            session = self.sessions.get(event.call.call_id)
            if session is None or (
                privacy is NotificationPrivacy.OFF and session.owner is not client
            ):
                return None
            info = self._project(session, client)
            if privacy is not NotificationPrivacy.SHOW_ALL:
                info.peer = ''
                info.alias = ''
            return CallStateEvent(
                call=info,
                request_id=event.request_id,
                revision=event.revision,
                epoch=event.epoch,
            )

    def is_owned_active(self, call_id: str, client: socket.socket) -> bool:
        """Checks the exact currently accepted call and owning IPC client."""
        with self.lock:
            session = self.sessions.get(call_id)
            return bool(
                session
                and session.owner is client
                and session.info.state is CallState.ACTIVE
            )

    def authorize_call(self, client: socket.socket, cmd: IpcCommand) -> bool:
        """Restricts lockscreen controls to the exact ongoing owned call only."""
        if isinstance(cmd, CancelCallCommand):
            with self.lock:
                session = self.sessions.get(cmd.call_id)
                return bool(
                    session
                    and session.owner is client
                    and session.info.state
                    in (CallState.CONNECTING, CallState.OUTGOING, CallState.ACTIVE)
                )
        if isinstance(
            cmd,
            (
                HangupCallCommand,
                MuteCallCommand,
                ReadCallAudioCommand,
                SendCallAudioCommand,
            ),
        ):
            return self.is_owned_active(cmd.call_id, client)
        return False

    def _available(self) -> bool:
        """Checks the bounded concurrent call budget under the owning lock."""
        return (
            not self.closed.is_set()
            and sum(s.info.state is not CallState.ENDED for s in self.sessions.values())
            < Constants.CALL_MAX_CONCURRENT
        )

    def _remember(self, session: CallSession) -> None:
        """Bounds historical metadata while preserving live identities."""
        while len(self.sessions) >= Constants.CALL_HISTORY_ITEMS:
            oldest = next(
                (
                    key
                    for key, value in self.sessions.items()
                    if value.info.state is CallState.ENDED
                ),
                None,
            )
            if oldest is None:
                break
            del self.sessions[oldest]
        self.sessions[session.info.call_id] = session

    def start(self, target: str, call_id: str, client: socket.socket) -> IpcEvent:
        """Creates one explicitly requested outgoing call without any chat mutation."""
        if not is_valid_message_id(call_id):
            return CallRejectedEvent(call_id=call_id, reason=CallReason.MALFORMED)
        resolved = self.cm.resolve_target_for_interaction(target)
        if resolved is None or resolved[1] == self.tm.onion:
            return CallRejectedEvent(call_id=call_id, reason=CallReason.INVALID_STATE)
        alias, onion = resolved
        with self.lock:
            previous = self.sessions.get(call_id)
            if previous is not None and previous.info.peer != onion:
                return CallRejectedEvent(
                    call_id=call_id, reason=CallReason.INVALID_STATE
                )
            if previous is not None:
                return (
                    CallStateEvent(call=self._project(previous, client))
                    if previous.owner is client
                    else CallRejectedEvent(call_id=call_id, reason=CallReason.NOT_OWNER)
                )
            seen = self.local_ids.setdefault(client, set())
            if call_id in seen:
                return CallRejectedEvent(
                    call_id=call_id, reason=CallReason.INVALID_STATE
                )
            if len(seen) >= Constants.CALL_OWNER_IDENTITIES_MAX:
                return CallRejectedEvent(call_id=call_id, reason=CallReason.BUSY)
            if not self._available():
                return CallRejectedEvent(call_id=call_id, reason=CallReason.BUSY)
            seen.add(call_id)
            session = CallSession(
                CallInfo(
                    call_id=call_id, peer=onion, alias=alias, state=CallState.CONNECTING
                ),
                owner=client,
            )
            self._remember(session)
            result = CallStateEvent(call=self._project(session, client))
        threading.Thread(
            target=transport.connect, args=(self, session), daemon=True
        ).start()
        return result

    def accept(self, call_id: str, client: socket.socket) -> IpcEvent:
        """Authorizes media only for the exact current incoming identity and client."""
        with self.lock:
            session = self.sessions.get(call_id)
            if session is None or session.info.state is not CallState.INCOMING:
                return CallRejectedEvent(
                    call_id=call_id, reason=CallReason.INVALID_STATE
                )
            if time.monotonic() >= session.deadline:
                expired = True
            else:
                expired = False
                session.owner = client
                session.info.state = CallState.ACTIVE
                session.info.started_at = time.time()
                session.frames.clear()
        if expired:
            self.finish(session, CallReason.TIMEOUT)
            return CallRejectedEvent(call_id=call_id, reason=CallReason.TIMEOUT)
        if not self.send(
            session,
            f'{TorCommand.CALL_ACCEPT.value} {session.wire_id} {session.tick()}\n',
        ):
            return CallRejectedEvent(call_id=call_id, reason=CallReason.TRANSPORT_LOST)
        self._emit(session)
        return CallStateEvent(call=self._project(session, client))

    def control(
        self, call_id: str, client: socket.socket, reason: CallReason
    ) -> IpcEvent:
        """Ends a qualified request or accepted call without ending borrowed chat."""
        with self.lock:
            session = self.sessions.get(call_id)
            if session is None:
                return CallRejectedEvent(
                    call_id=call_id, reason=CallReason.INVALID_STATE
                )
            allowed_states: tuple[CallState, ...]
            if reason is CallReason.REJECTED:
                allowed_states = (CallState.INCOMING,)
                owner = None
            else:
                allowed_states = (
                    (CallState.CONNECTING, CallState.OUTGOING, CallState.ACTIVE)
                    if reason is CallReason.CANCELLED
                    else (CallState.ACTIVE,)
                )
                owner = client
            valid = session.info.state in allowed_states and (
                owner is None or session.owner is owner
            )
            if not valid:
                return CallRejectedEvent(
                    call_id=call_id,
                    reason=CallReason.NOT_OWNER
                    if session.owner is not client
                    else CallReason.INVALID_STATE,
                )
        if not self.finish(
            session, reason, notify=True, owner=owner, allowed_states=allowed_states
        ):
            return CallRejectedEvent(call_id=call_id, reason=CallReason.INVALID_STATE)
        return CallStateEvent(call=self._project(session, client))

    def mute(self, call_id: str, client: socket.socket, muted: bool) -> IpcEvent:
        """Revokes capture emission while retaining the accepted identity and receive side."""
        with self.lock:
            if not self.is_owned_active(call_id, client):
                return CallRejectedEvent(call_id=call_id, reason=CallReason.NOT_OWNER)
            session = self.sessions[call_id]
            session.info.muted = muted
            result = CallStateEvent(call=self._project(session, client))
        self._emit(session)
        return result

    def send(
        self, session: CallSession, line: str, claim: Callable[[], bool] | None = None
    ) -> bool:
        """Enqueues a serialized frame outside call locks with a late eligibility claim."""
        connection = session.connection
        if connection is None:
            return False
        try:
            self.transport_state.send_frame(connection, line.encode('ascii'), claim)
            return True
        except (OSError, ValueError, RuntimeError):
            self.finish(session, CallReason.TRANSPORT_LOST)
            return False

    def finish(
        self,
        session: CallSession,
        reason: CallReason,
        *,
        notify: bool = False,
        owner: socket.socket | None = None,
        allowed_states: tuple[CallState, ...] | None = None,
    ) -> bool:
        """Atomically qualifies termination, clears media, and releases an exclusive transport."""
        with self.lock:
            if (
                self.sessions.get(session.info.call_id) is not session
                or session.info.state is CallState.ENDED
            ):
                return False
            if allowed_states is not None and session.info.state not in allowed_states:
                return False
            if owner is not None and session.owner is not owner:
                return False
            if (
                reason is CallReason.CANCELLED
                and session.info.state is CallState.ACTIVE
            ):
                reason = CallReason.HUNG_UP
            session.info.state = CallState.ENDED
            session.info.reason = reason
            session.frames.clear()
            connection = session.connection
        if notify and connection is not None:
            frame = f'{TorCommand.CALL_END.value} {session.wire_id} {reason.value}\n'.encode(
                'ascii'
            )
            try:
                if session.borrowed:
                    self.transport_state.send_frame(connection, frame)
                else:
                    self.transport_state.finish_connection(connection, frame)
            except (OSError, ValueError, RuntimeError):
                pass
        if connection is not None and not session.borrowed:
            self.transport_state.retire_connection(connection, preserve_final=notify)
        self._emit(session)
        return True

    def disconnect_client(self, client: socket.socket) -> None:
        """Revokes all calls owned by a disconnected local frontend."""
        with self.lock:
            sessions = [s for s in self.sessions.values() if s.owner is client]
        for session in sessions:
            self.finish(session, CallReason.CLIENT_LOST, notify=True)

    def close(self) -> None:
        """Ends calls before hard profile lock, profile switch, shutdown, or purge."""
        self.closed.set()
        with self.lock:
            sessions = list(self.sessions.values())
        for session in sessions:
            self.finish(session, CallReason.PROFILE_LOCKED, notify=True)

    def process_frame(
        self, onion: str, connection: socket.socket, line: str, borrowed: bool = True
    ) -> bool:
        """Admits dedicated call signaling independently of normal message frames."""
        return signaling.process_frame(self, onion, connection, line, borrowed)

    def accept_transport(
        self, onion: str, connection: socket.socket, stream: TcpStreamReader
    ) -> None:
        """Owns a CALL-only authenticated socket without introducing LIVE permission."""
        transport.receive(self, onion, connection, stream)

    def retain_after_chat_end(self, connection: socket.socket) -> str | None:
        """Transfers an existing shared transport lease to its ongoing call only."""
        with self.lock:
            session = next(
                (
                    s
                    for s in self.sessions.values()
                    if s.connection is connection
                    and s.borrowed
                    and s.info.state is not CallState.ENDED
                ),
                None,
            )
            if session is None:
                return None
            session.borrowed = False
            self.exclusive_sockets.add(connection)
            return session.wire_id

    def owns_transport(self, connection: socket.socket) -> bool:
        """Keeps an exclusive socket outside chat recovery after call revocation."""
        with self.lock:
            return connection in self.exclusive_sockets

    def keeps_transport(self, connection: socket.socket) -> bool:
        """Checks whether an exact socket remains authorized solely for call traffic."""
        with self.lock:
            return any(
                s.connection is connection and s.info.state is not CallState.ENDED
                for s in self.sessions.values()
            )

    def transport_lost(self, connection: socket.socket) -> None:
        """Ends the matching call only; a replacement cannot inherit old call consent."""
        with self.lock:
            sessions = [s for s in self.sessions.values() if s.connection is connection]
        for session in sessions:
            self.finish(session, CallReason.TRANSPORT_LOST)

    def send_audio(
        self, call_id: str, client: socket.socket, sequence: int, data: str
    ) -> CallAudioSentEvent | CallRejectedEvent:
        """Delegates bounded, exact-owner outgoing PCM frame admission."""
        return media.send_audio(self, call_id, client, sequence, data)

    def read_audio(
        self, call_id: str, client: socket.socket, max_frames: int
    ) -> CallAudioEvent | CallRejectedEvent:
        """Consumes fresh frames; arbitrary clients cannot read call payload."""
        return media.read_audio(self, call_id, client, max_frames)
