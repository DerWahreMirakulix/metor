"""
Module defining the NetworkCommandHandler.
Encapsulates all logic for initiating and managing Tor connections, Drops, and RAM buffers.
Emits strictly typed Domain Transfer Objects via IPC.
"""

import base64
import socket
import threading
from typing import Callable, Dict, Optional, Tuple, TYPE_CHECKING

from metor.core.api import (
    BeginVoiceCommand,
    CommitVoiceCommand,
    CancelVoiceCommand,
    AppendVoiceChunkCommand,
    ContentType,
    EventType,
    GetChatStartupStateCommand,
    GetRuntimeSnapshotCommand,
    GetVoiceChunkCommand,
    ReleaseVoiceCommand,
    IpcCommand,
    IpcEvent,
    create_event,
    InitCommand,
    InitEvent,
    ProtocolMismatchEvent,
    GetConnectionsCommand,
    ConnectionsStateEvent,
    ConnectCommand,
    DisconnectCommand,
    DismissLiveContextCommand,
    AcceptCommand,
    RejectCommand,
    Delivery,
    FallbackCommand,
    FinalizeVoiceCommand,
    RegisterLiveConsumerCommand,
    SendMessageCommand,
    SwitchCommand,
    SwitchSuccessEvent,
    RetunnelCommand,
    RuntimeErrorCode,
    MessageOperationReason,
    request_context,
    stamp_request_id,
    GetTransportStateCommand,
    TextContent,
    VoiceContent,
)
from metor.core.tor import TorManager
from metor.core.daemon.managed.network import NetworkManager
from metor.data import (
    HistoryManager,
    HistoryActor,
    HistoryEvent,
    ContactManager,
    MessageManager,
    MessageDirection,
    MessageStatus,
    SettingKey,
)
from metor.utils import clean_onion
from metor.versioning import (
    IPC_PROTOCOL_MIN_SUPPORTED,
    IPC_PROTOCOL_VERSION,
    negotiate_protocol_generation,
)

# Local Package Imports
from metor.core.daemon.managed.outbox import OutboxWorker
from .snapshot import RuntimeSnapshotProjectionMixin

if TYPE_CHECKING:
    from metor.data.profile import Config


class NetworkCommandHandler(RuntimeSnapshotProjectionMixin):
    """Processes network-related IPC commands from the UI using strict DTOs."""

    @staticmethod
    def _run_request_target(
        request_id: Optional[str],
        target: Callable[..., None],
        *args: object,
    ) -> None:
        """
        Executes one asynchronous network action under the originating request context.

        Args:
            request_id (Optional[str]): The originating request identifier.
            target (Callable[..., None]): The action to execute.
            *args (object): Positional arguments forwarded to the action.

        Returns:
            None
        """
        with request_context(request_id):
            target(*args)

    def __init__(
        self,
        tm: TorManager,
        cm: ContactManager,
        hm: HistoryManager,
        mm: MessageManager,
        network: NetworkManager,
        outbox: OutboxWorker,
        broadcast_cb: Callable[[IpcEvent], None],
        send_to_cb: Callable[[socket.socket, IpcEvent], None],
        register_session_consumer_cb: Callable[[socket.socket], None],
        config: 'Config',
        current_revision_cb: Optional[Callable[[], int]] = None,
    ) -> None:
        """
        Initializes the NetworkCommandHandler.

        Args:
            tm (TorManager): Tor process manager.
            cm (ContactManager): Address book manager.
            hm (HistoryManager): Event logging.
            mm (MessageManager): Offline messages storage.
            network (NetworkManager): The core network orchestrator.
            outbox (OutboxWorker): The offline drop tunnel worker.
            broadcast_cb (Callable[[IpcEvent], None]): Hook to broadcast IPC events.
            send_to_cb (Callable[[socket.socket, IpcEvent], None]): Hook to send an IPC event to a specific client.
            register_session_consumer_cb (Callable[[socket.socket], None]): Hook to mark one IPC session as an interactive live consumer.
            config (Config): The profile configuration instance.
            current_revision_cb (Optional[Callable[[], int]]): Current daemon
                event sequence used to build a race-safe aggregate snapshot.

        Returns:
            None
        """
        self._tm: TorManager = tm
        self._cm: ContactManager = cm
        self._hm: HistoryManager = hm
        self._mm: MessageManager = mm
        self._network: NetworkManager = network
        self._outbox: OutboxWorker = outbox
        self._broadcast: Callable[[IpcEvent], None] = broadcast_cb
        self._send_to: Callable[[socket.socket, IpcEvent], None] = send_to_cb
        self._register_session_consumer: Callable[[socket.socket], None] = (
            register_session_consumer_cb
        )
        self._config: 'Config' = config
        self._current_revision: Callable[[], int] = current_revision_cb or (lambda: 0)
        self._client_focuses: Dict[socket.socket, str] = {}
        self._focus_lock: threading.Lock = threading.Lock()

    def _broadcast_event(self, event: IpcEvent) -> None:
        """
        Emits one broadcast event after applying request correlation metadata.

        Args:
            event (IpcEvent): The event to emit.

        Returns:
            None
        """
        self._broadcast(stamp_request_id(event))

    def _send_event(self, conn: socket.socket, event: IpcEvent) -> None:
        """
        Sends one direct response event after applying request correlation metadata.

        Args:
            conn (socket.socket): The target IPC socket.
            event (IpcEvent): The event to emit.

        Returns:
            None
        """
        self._send_to(conn, stamp_request_id(event))

    def _start_request_thread(
        self,
        request_id: Optional[str],
        target: Callable[..., None],
        *args: object,
    ) -> None:
        """
        Starts one background worker that preserves the originating request context.

        Args:
            request_id (Optional[str]): The originating request identifier.
            target (Callable[..., None]): The action to execute.
            *args (object): Positional arguments forwarded to the action.

        Returns:
            None
        """
        threading.Thread(
            target=self._run_request_target,
            args=(request_id, target, *args),
            daemon=True,
        ).start()

    def _set_client_focus(self, conn: socket.socket, onion: Optional[str]) -> None:
        """
        Synchronizes one IPC client's active peer focus with the daemon state.

        Args:
            conn (socket.socket): The IPC client socket.
            onion (Optional[str]): The newly focused onion or None to clear focus.

        Returns:
            None
        """
        with self._focus_lock:
            previous_onion: Optional[str] = self._client_focuses.get(conn)

            if previous_onion and previous_onion != onion:
                self._network.remove_ui_focus(previous_onion)

            if onion is None:
                self._client_focuses.pop(conn, None)
                return

            if previous_onion != onion:
                self._network.add_ui_focus(onion)

            self._client_focuses[conn] = onion

    def clear_client_focus(self, conn: socket.socket) -> None:
        """
        Removes any tracked focus for a disconnected IPC client.

        Args:
            conn (socket.socket): The disconnected IPC client socket.

        Returns:
            None
        """
        self._set_client_focus(conn, None)

    def clear_all_focus(self) -> None:
        """Clears focus owned by every attached IPC client.

        Args:
            None

        Returns:
            None
        """
        with self._focus_lock:
            connections = list(self._client_focuses)
        for conn in connections:
            self._set_client_focus(conn, None)

    def _retunnel_target(self, alias: str, onion: str) -> None:
        """
        Routes retunnel requests to the live controller or the drop tunnel worker.

        Args:
            alias (str): The strict alias resolved for the peer.
            onion (str): The strict onion identity.

        Returns:
            None
        """
        if self._network.is_connected_or_pending(onion):
            self._outbox.reset_tunnel(onion)
            self._network.retunnel(onion)
            return

        if not self._network.has_drop_tunnel(onion):
            self._broadcast_event(
                create_event(
                    EventType.RETUNNEL_FAILED,
                    {
                        'alias': alias,
                        'onion': onion,
                        'error_code': RuntimeErrorCode.NO_CACHED_DROP_TUNNEL,
                    },
                )
            )
            return

        self._outbox.retunnel(onion, alias)

    def _is_self_target(self, target: str) -> bool:
        """
        Safely checks if a target (alias or onion) points to our own identity.

        Args:
            target (str): The alias or onion to check.

        Returns:
            bool: True if it matches our own onion, False otherwise.
        """
        if not target or not self._tm.onion:
            return False

        if clean_onion(target) == clean_onion(self._tm.onion):
            return True

        onion_by_alias: Optional[str] = self._cm.get_onion_by_alias(target)
        if onion_by_alias and onion_by_alias == self._tm.onion:
            return True

        return False

    def handle(self, cmd: IpcCommand, conn: socket.socket) -> None:
        """
        Routes the network command to the NetworkManager or MessageManager and returns DTOs.

        Args:
            cmd (IpcCommand): The network-related IPC command.
            conn (socket.socket): The IPC client connection to respond to.

        Returns:
            None
        """
        resolved: Optional[Tuple[str, str]]

        if isinstance(cmd, InitCommand):
            negotiated_version: Optional[int] = negotiate_protocol_generation(
                IPC_PROTOCOL_VERSION,
                IPC_PROTOCOL_MIN_SUPPORTED,
                cmd.current_version,
                cmd.min_supported,
            )
            if negotiated_version is None:
                self._send_event(
                    conn,
                    ProtocolMismatchEvent(
                        daemon_current_version=IPC_PROTOCOL_VERSION,
                        daemon_min_supported=IPC_PROTOCOL_MIN_SUPPORTED,
                        client_current_version=cmd.current_version,
                        client_min_supported=cmd.min_supported,
                    ),
                )
            else:
                self._send_event(
                    conn,
                    InitEvent(
                        onion=self._tm.onion,
                        negotiated_version=negotiated_version,
                        daemon_current_version=IPC_PROTOCOL_VERSION,
                        daemon_min_supported=IPC_PROTOCOL_MIN_SUPPORTED,
                        profile=self._config._paths.profile_name,
                        capabilities=[
                            'text_content',
                            'voice_content',
                            'voice_inbound_descriptor',
                            'voice_bounded_read',
                            'voice_resume',
                            'voice_terminal_commit',
                            'voice_draft_commit',
                            'restricted_client',
                            'restricted_voice',
                            'device_lifecycle',
                            'runtime_snapshot',
                            'runtime_epoch',
                            'runtime_state_invalidation',
                            'runtime_lock',
                        ],
                    ),
                )

        elif isinstance(cmd, GetChatStartupStateCommand):
            self._send_event(conn, self._build_chat_startup_state())

        elif isinstance(cmd, GetRuntimeSnapshotCommand):
            self._send_event(conn, self._build_runtime_snapshot())

        elif isinstance(cmd, RegisterLiveConsumerCommand):
            self._register_session_consumer(conn)

        elif isinstance(cmd, BeginVoiceCommand):
            if cmd.delivery is Delivery.DROP and not self._config.get_bool(
                SettingKey.ALLOW_DROPS
            ):
                self._send_event(conn, create_event(EventType.DROPS_DISABLED))
                return
            if self._is_self_target(cmd.target):
                self._send_event(
                    conn,
                    create_event(
                        EventType.CANNOT_DROP_SELF
                        if cmd.delivery is Delivery.DROP
                        else EventType.CANNOT_CONNECT_SELF
                    ),
                )
                return
            self._network.begin_voice(cmd.target, cmd.delivery, cmd.msg_id, cmd.codec)

        elif isinstance(cmd, AppendVoiceChunkCommand):
            self._network.append_voice(cmd.msg_id, cmd.offset, cmd.data)

        elif isinstance(cmd, FinalizeVoiceCommand):
            self._network.finalize_voice(cmd.msg_id, cmd.duration_ms)

        elif isinstance(cmd, CommitVoiceCommand):
            resolved = self._cm.resolve_target(cmd.target)
            if resolved is not None and self._network.commit_voice_draft(
                cmd.target, cmd.msg_id
            ):
                self._send_event(
                    conn,
                    create_event(
                        EventType.VOICE_COMMITTED,
                        {
                            'alias': resolved[0],
                            'onion': resolved[1],
                            'msg_id': cmd.msg_id,
                        },
                    ),
                )
            else:
                self._send_event(
                    conn,
                    create_event(
                        EventType.VOICE_OPERATION_REJECTED,
                        {
                            'msg_id': cmd.msg_id,
                            'reason': MessageOperationReason.NOT_FINALIZED.value,
                        },
                    ),
                )

        elif isinstance(cmd, CancelVoiceCommand):
            resolved = self._cm.resolve_target(cmd.target)
            if resolved is not None and self._network.cancel_voice_draft(
                cmd.target, cmd.msg_id
            ):
                self._send_event(
                    conn,
                    create_event(
                        EventType.VOICE_CANCELLED,
                        {
                            'alias': resolved[0],
                            'onion': resolved[1],
                            'msg_id': cmd.msg_id,
                        },
                    ),
                )
            else:
                self._send_event(
                    conn,
                    create_event(
                        EventType.VOICE_OPERATION_REJECTED,
                        {
                            'msg_id': cmd.msg_id,
                            'reason': MessageOperationReason.NOT_FOUND.value,
                        },
                    ),
                )

        elif isinstance(cmd, GetVoiceChunkCommand):
            resolved = self._cm.resolve_target(cmd.target)
            if resolved is None:
                self._send_event(
                    conn,
                    create_event(
                        EventType.VOICE_OPERATION_REJECTED,
                        {
                            'msg_id': cmd.msg_id,
                            'reason': MessageOperationReason.NOT_FOUND.value,
                        },
                    ),
                )
                return
            alias, onion = resolved
            direction = MessageDirection(cmd.direction.value)
            content, delivery, data, next_offset, complete, reason = (
                self._network.read_voice_chunk(
                    onion, cmd.msg_id, direction, cmd.offset, cmd.max_bytes
                )
            )
            if (
                reason is not None
                or content is None
                or delivery is None
                or data is None
            ):
                self._send_event(
                    conn,
                    create_event(
                        EventType.VOICE_OPERATION_REJECTED,
                        {
                            'msg_id': cmd.msg_id,
                            'onion': onion,
                            'reason': (
                                reason or MessageOperationReason.NOT_FOUND
                            ).value,
                        },
                    ),
                )
                return
            self._send_event(
                conn,
                create_event(
                    EventType.VOICE_DATA,
                    {
                        'alias': alias,
                        'onion': onion,
                        'msg_id': cmd.msg_id,
                        'direction': cmd.direction.value,
                        'delivery': delivery.value,
                        'codec': content.codec,
                        'offset': cmd.offset,
                        'next_offset': next_offset,
                        'size_bytes': content.size_bytes,
                        'data': base64.b64encode(data).decode('ascii'),
                        'complete': complete,
                        'duration_ms': content.duration_ms,
                    },
                ),
            )

        elif isinstance(cmd, ReleaseVoiceCommand):
            resolved = self._cm.resolve_target(cmd.target)
            if resolved is None:
                self._send_event(
                    conn,
                    create_event(
                        EventType.VOICE_OPERATION_REJECTED,
                        {
                            'msg_id': cmd.msg_id,
                            'reason': MessageOperationReason.NOT_FOUND.value,
                        },
                    ),
                )
                return
            alias, onion = resolved
            if not self._network.release_inbound_voice_item(onion, cmd.msg_id):
                self._send_event(
                    conn,
                    create_event(
                        EventType.VOICE_OPERATION_REJECTED,
                        {
                            'msg_id': cmd.msg_id,
                            'onion': onion,
                            'reason': MessageOperationReason.NOT_FINALIZED.value,
                        },
                    ),
                )
                return
            self._send_event(
                conn,
                create_event(
                    EventType.VOICE_RELEASED,
                    {'alias': alias, 'onion': onion, 'msg_id': cmd.msg_id},
                ),
            )
            self._broadcast_event(
                create_event(
                    EventType.RUNTIME_STATE_CHANGED,
                    {'scope': 'messages', 'onion': onion},
                )
            )

        elif isinstance(cmd, SendMessageCommand) and isinstance(
            cmd.content, VoiceContent
        ):
            self._send_event(
                conn,
                create_event(
                    EventType.VOICE_OPERATION_REJECTED,
                    {
                        'msg_id': cmd.msg_id,
                        'reason': MessageOperationReason.UNSUPPORTED_CONTENT.value,
                    },
                ),
            )

        elif isinstance(cmd, GetTransportStateCommand):
            for event in self._build_transport_state_events(cmd.peer):
                self._send_event(conn, event)

        elif isinstance(cmd, GetConnectionsCommand):
            self._send_event(
                conn,
                ConnectionsStateEvent(
                    active=self._network.get_active_aliases(),
                    pending=self._network.get_pending_aliases(),
                    contacts=self._cm.get_all_contacts(),
                    is_header=cmd.is_header,
                ),
            )

        elif isinstance(cmd, ConnectCommand):
            if self._is_self_target(cmd.target):
                self._send_event(conn, create_event(EventType.CANNOT_CONNECT_SELF))
                return

            resolved = self._cm.resolve_target_for_interaction(cmd.target)
            if not resolved:
                self._send_event(
                    conn,
                    create_event(
                        EventType.INVALID_TARGET,
                        {'target': cmd.target},
                    ),
                )
                return

            self._start_request_thread(
                cmd.request_id,
                self._network.connect_to,
                cmd.target,
            )

        elif isinstance(cmd, DisconnectCommand):
            self._network.disconnect(cmd.target, initiated_by_self=True)

        elif isinstance(cmd, AcceptCommand):
            self._network.accept(cmd.target)

        elif isinstance(cmd, RejectCommand):
            self._network.reject(cmd.target, initiated_by_self=True)

        elif (
            isinstance(cmd, SendMessageCommand)
            and cmd.delivery is Delivery.LIVE
            and isinstance(cmd.content, TextContent)
        ):
            self._network.send_message(cmd.target, cmd.content.text, cmd.msg_id)

        elif isinstance(cmd, FallbackCommand):
            success, event_type, params = self._network.force_fallback(
                cmd.target, cmd.msg_ids
            )
            self._send_event(conn, create_event(event_type, params))
            if success:
                self._broadcast(
                    create_event(
                        EventType.RUNTIME_STATE_CHANGED,
                        {
                            'scope': 'messages',
                            'onion': params.get('onion'),
                        },
                    )
                )

        elif isinstance(cmd, DismissLiveContextCommand):
            resolved = self._cm.resolve_target(cmd.target)
            if not resolved:
                self._send_event(
                    conn, create_event(EventType.PEER_NOT_FOUND, {'target': cmd.target})
                )
                return
            alias, onion = resolved
            if self._network.is_connected_or_recovering(onion):
                self._send_event(
                    conn,
                    create_event(
                        EventType.LIVE_CONTEXT_DISMISS_REJECTED,
                        {
                            'alias': alias,
                            'onion': onion,
                            'reason': MessageOperationReason.ACTIVE_LIVE_CONTEXT.value,
                        },
                    ),
                )
                return
            if self._mm.get_pending_live_outbox(onion):
                self._send_event(
                    conn,
                    create_event(
                        EventType.LIVE_CONTEXT_DISMISS_REJECTED,
                        {
                            'alias': alias,
                            'onion': onion,
                            'reason': MessageOperationReason.OUTBOUND_PENDING_LIVE.value,
                        },
                    ),
                )
                return
            removed_count = self._mm.dismiss_inbound_live(onion)
            self._network.dismiss_inbound_voice(onion)
            self._send_event(
                conn,
                create_event(
                    EventType.LIVE_CONTEXT_DISMISSED,
                    {
                        'alias': alias,
                        'onion': onion,
                        'removed_count': removed_count,
                    },
                ),
            )
            self._broadcast(
                create_event(
                    EventType.RUNTIME_STATE_CHANGED,
                    {'scope': 'live_contexts', 'onion': onion},
                )
            )

        elif isinstance(cmd, RetunnelCommand):
            resolved = self._cm.resolve_target_for_interaction(cmd.target)
            if not resolved:
                self._send_event(
                    conn,
                    create_event(
                        EventType.INVALID_TARGET,
                        {'target': cmd.target},
                    ),
                )
                return

            alias, onion = resolved
            self._start_request_thread(
                cmd.request_id,
                self._retunnel_target,
                alias,
                onion,
            )

        elif isinstance(cmd, SendMessageCommand) and isinstance(
            cmd.content, TextContent
        ):
            if not self._config.get_bool(SettingKey.ALLOW_DROPS):
                self._send_event(conn, create_event(EventType.DROPS_DISABLED))
                return

            if self._is_self_target(cmd.target):
                self._send_event(conn, create_event(EventType.CANNOT_DROP_SELF))
                return

            resolved = self._cm.resolve_target_for_interaction(cmd.target)

            if resolved:
                alias, onion = resolved
                self._outbox.remember_message_request_id(
                    cmd.msg_id,
                    cmd.request_id,
                )
                self._mm.queue_message(
                    contact_onion=str(onion),
                    direction=MessageDirection.OUT,
                    delivery=Delivery.DROP,
                    content_type=ContentType.TEXT,
                    payload=cmd.content.text,
                    status=MessageStatus.PENDING,
                    msg_id=cmd.msg_id,
                )
                if self._config.get_bool(SettingKey.RECORD_DROP_HISTORY):
                    self._hm.log_event(
                        HistoryEvent.QUEUED,
                        onion,
                        actor=HistoryActor.LOCAL,
                    )

                self._send_event(
                    conn,
                    create_event(
                        EventType.DROP_QUEUED,
                        {'alias': alias, 'onion': onion},
                    ),
                )
            else:
                self._send_event(
                    conn,
                    create_event(
                        EventType.INVALID_TARGET,
                        {'target': cmd.target},
                    ),
                )

        elif isinstance(cmd, SwitchCommand):
            if cmd.target is None or cmd.target == '..':
                self._set_client_focus(conn, None)
                self._send_event(conn, SwitchSuccessEvent(alias=None))
            else:
                if self._is_self_target(cmd.target):
                    self._send_event(
                        conn,
                        create_event(EventType.CANNOT_SWITCH_SELF),
                    )
                    return

                resolved = self._cm.resolve_target_for_interaction(cmd.target)
                if not resolved:
                    self._send_event(
                        conn,
                        create_event(
                            EventType.INVALID_TARGET,
                            {'target': cmd.target},
                        ),
                    )
                    return

                alias, onion = resolved
                self._set_client_focus(conn, onion)
                self._send_event(
                    conn,
                    SwitchSuccessEvent(alias=alias, onion=onion),
                )
