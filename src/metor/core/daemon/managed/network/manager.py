"""
Module defining the NetworkManager Facade.
Provides a clean, strictly-typed API to the Daemon Engine while abstracting
the complex interactions between the Listener, Receiver, Controller, and Router.
"""

import threading
import socket
from contextlib import contextmanager
from typing import Dict, Iterator, List, Callable, Optional, Tuple, TYPE_CHECKING

from metor.core.api import (
    ConnectionActor,
    ConnectionOrigin,
    ConnectionReasonCode,
    Delivery,
    EventType,
    IpcEvent,
    JsonValue,
    MessageOperationReason,
    VoiceContent,
)
from metor.core.daemon.managed.crypto import Crypto
from metor.core.daemon.managed.models import TunnelState, SessionState
from metor.core.tor import TorManager
from metor.data import (
    HistoryManager,
    ContactManager,
    MessageDirection,
    MessageManager,
    PendingLiveRecord,
)
from metor.data.blob import BlobStore

# Local Package Imports
from metor.core.daemon.managed.network.calls import CallController
from metor.core.daemon.managed.network.state import (
    PendingConnectionSnapshot,
    StateTracker,
)
from metor.core.daemon.managed.network.router import MessageRouter
from metor.core.daemon.managed.network.controller.base import ConnectionController
from metor.core.daemon.managed.network.receiver import StreamReceiver
from metor.core.daemon.managed.network.listener import InboundListener
from metor.core.daemon.managed.notify import NotificationPayload
from .removal import LiveContextRemoval

if TYPE_CHECKING:
    from metor.data.profile import Config


class NetworkManager:
    """Facade orchestrating network states, socket lifecycles, and application routing."""

    def __init__(
        self,
        tm: TorManager,
        cm: ContactManager,
        hm: HistoryManager,
        mm: MessageManager,
        crypto: Crypto,
        broadcast_callback: Callable[[IpcEvent], None],
        has_clients_callback: Callable[[], bool],
        has_live_consumers_callback: Callable[[], bool],
        notify_callback: Callable[[NotificationPayload], None],
        stop_flag: threading.Event,
        config: 'Config',
        state: Optional[StateTracker] = None,
        blob_store: Optional[BlobStore] = None,
        purge_fence: Optional[threading.Event] = None,
        operation_lock: Optional[threading.RLock] = None,
    ) -> None:
        """
        Initializes the NetworkManager and its isolated sub-components.

        Args:
            tm (TorManager): Tor process manager.
            cm (ContactManager): Address book manager.
            hm (HistoryManager): Event history manager.
            mm (MessageManager): Offline messages manager.
            crypto (Crypto): Cryptographic challenge/response engine.
            broadcast_callback (Callable[[IpcEvent], None]): Callback to broadcast IPC events.
            has_clients_callback (Callable[[], bool]): Callback to check for active UI clients.
            has_live_consumers_callback (Callable[[], bool]): Callback to check for interactive live consumers.
            notify_callback (Callable[[NotificationPayload], None]): Callback delivering detached notifications.
            stop_flag (threading.Event): Global daemon termination flag.
            config (Config): The profile configuration instance.
            state (Optional[StateTracker]): Optional shared transport state.
            blob_store (Optional[BlobStore]): Active profile external object store.
            purge_fence (Optional[threading.Event]): Destructive lifecycle fence.
            operation_lock (Optional[threading.RLock]): State publication barrier.

        Returns:
            None
        """
        self._cm: ContactManager = cm
        self._operation_lock = operation_lock or threading.RLock()
        self._state: StateTracker = state or StateTracker()
        self.calls = CallController(
            tm, cm, crypto, self._state, broadcast_callback, stop_flag
        )

        self._router: MessageRouter = MessageRouter(
            cm=cm,
            hm=hm,
            mm=mm,
            state=self._state,
            broadcast_callback=broadcast_callback,
            has_clients_callback=has_clients_callback,
            has_live_consumers_callback=has_live_consumers_callback,
            notify_callback=notify_callback,
            config=config,
            blob_store=blob_store,
            purge_fence=purge_fence,
            operation_lock=self._operation_lock,
        )

        self._controller: ConnectionController = ConnectionController(
            tm=tm,
            cm=cm,
            hm=hm,
            mm=mm,
            crypto=crypto,
            state=self._state,
            router=self._router,
            broadcast_callback=broadcast_callback,
            has_live_consumers_callback=has_live_consumers_callback,
            stop_flag=stop_flag,
            config=config,
            operation_lock=self._operation_lock,
            retain_call_transport=self.calls.retain_after_chat_end,
        )
        self.calls.chat_end = lambda onion, conn: self._controller.disconnect(
            onion,
            initiated_by_self=False,
            socket_to_close=conn,
            origin=ConnectionOrigin.INCOMING,
        )
        self._state.set_peer_writer_failure_callback(
            lambda onion, conn: self._controller.disconnect(
                onion, initiated_by_self=False, is_fallback=True, socket_to_close=conn
            )
        )

        self._receiver: StreamReceiver = StreamReceiver(
            cm=cm,
            hm=hm,
            state=self._state,
            router=self._router,
            broadcast_callback=broadcast_callback,
            disconnect_cb=self._controller.disconnect,
            reject_cb=self._controller.reject,
            config=config,
            call_frame_callback=self.calls.process_frame,
            call_lost_callback=self.calls.transport_lost,
            call_keeps_transport_callback=self.calls.keeps_transport,
            call_owns_transport_callback=self.calls.owns_transport,
        )

        self._controller.set_receiver(self._receiver)

        self._listener: InboundListener = InboundListener(
            tm=tm,
            cm=cm,
            hm=hm,
            crypto=crypto,
            state=self._state,
            router=self._router,
            receiver=self._receiver,
            broadcast_callback=broadcast_callback,
            has_clients_callback=has_clients_callback,
            has_live_consumers_callback=has_live_consumers_callback,
            notify_callback=notify_callback,
            enqueue_live_reconnect_callback=self._controller._enqueue_live_reconnect,
            stop_flag=stop_flag,
            config=config,
            call_transport_callback=self.calls.accept_transport,
            operation_lock=self._operation_lock,
        )
        self._removal = LiveContextRemoval(
            mm,
            self._state,
            self._operation_lock,
            self.is_connected_or_recovering,
            self.cancel_pending_live_voice,
            self.dismiss_inbound_voice,
        )

    def start_listener(self) -> None:
        """
        Starts the local Tor TCP listener in a background thread.

        Args:
            None

        Returns:
            None
        """
        self._listener.start_listener()

    def connect_to(self, target: str) -> None:
        """
        Initiates an outbound Tor connection to a peer.

        Args:
            target (str): The alias or onion address.

        Returns:
            None
        """
        self._controller.connect_to(target)

    def accept(
        self, target: str, *, expected_pending: Optional[socket.socket] = None
    ) -> None:
        """
        Approves a pending incoming connection request.

        Args:
            target (str): The target alias or onion.

        Returns:
            None
        """
        self._controller.accept(target, expected_pending=expected_pending)

    def reject(
        self,
        target: str,
        initiated_by_self: bool = True,
        *,
        expected_pending: Optional[socket.socket] = None,
    ) -> None:
        """
        Rejects a connection request.

        Args:
            target (str): The target alias or onion.
            initiated_by_self (bool): Whether the local user initiated the rejection.

        Returns:
            None
        """
        self._controller.reject(
            target, initiated_by_self, expected_pending=expected_pending
        )

    def disconnect(
        self,
        target: str,
        initiated_by_self: bool = True,
        system_reason: Optional[ConnectionReasonCode] = None,
    ) -> None:
        """
        Terminates an active connection safely.

        Args:
            target (str): The target alias or onion.
            initiated_by_self (bool): Whether the local user initiated the disconnect.
            system_reason (Optional[ConnectionReasonCode]): Local system-policy reason.

        Returns:
            None
        """
        self._controller.disconnect(
            target,
            initiated_by_self,
            origin=(ConnectionOrigin.MANUAL if initiated_by_self else None),
            system_reason=system_reason,
        )

    def disconnect_all(self) -> None:
        """
        Forcefully disconnects all active and pending peers safely upon shutdown.

        Args:
            None

        Returns:
            None
        """
        self.calls.close()
        self._controller.disconnect_all()
        self._router.finalize_pending_live_messages()

    def disconnect_qualified(
        self, target: str, context_generation: Optional[int], attempt_id: Optional[str]
    ) -> bool:
        """Delegates exact End/Cancel admission to the existing atomic lifecycle owner.

        Args:
            target: Original canonical peer.
            context_generation: Expected logical active/recovering generation.
            attempt_id: Expected outbound calling attempt.
        Returns:
            bool: Whether the original identity was still eligible.
        """
        return self._controller.disconnect_qualified(
            target, context_generation, attempt_id
        )

    def get_outbound_attempt_id(self, onion: str) -> Optional[str]:
        """Projects the current opaque calling identity without changing lifecycle state.

        Args:
            onion: Canonical peer.
        Returns:
            Optional[str]: Current outbound attempt identity.
        """
        return self._state.get_outbound_attempt_id(onion)

    def abort_all(self) -> None:
        """Preempts sockets without reconnect, fallback, or delivery finalization.

        Args:
            None

        Returns:
            None
        """
        self.calls.close()
        self._state.abort_all_sockets()

    def retunnel(self, target: str, context_generation: Optional[int] = None) -> None:
        """
        Forces a Tor circuit rotation and reconnects.

        Args:
            target (str): The target alias or onion address.
            context_generation: Optional exact active LIVE identity from the caller.

        Returns:
            None
        """
        self._controller.retunnel(target, context_generation=context_generation)

    def is_retunneling(self, onion: str) -> bool:
        """Projects route replacement already admitted by the connection owner.

        Args:
            onion: Canonical LIVE peer.
        Returns:
            bool: Whether circuit rotation or its recognized recovery is in progress.
        """
        return self._state.is_retunneling(onion)

    def is_connected_or_pending(self, onion: str) -> bool:
        """
        Checks whether a peer currently has a live or pending session state.

        Args:
            onion (str): The strict onion identity.

        Returns:
            bool: True if the peer is currently active or pending.
        """
        return self._state.is_connected_or_pending(onion)

    def is_connected_or_recovering(self, onion: str) -> bool:
        """Checks whether a peer has active, pending, or genuine recovery state.

        Args:
            onion (str): The strict onion identity.

        Returns:
            bool: True while dismissing LIVE state would race session recovery.
        """
        return (
            self._state.is_connected_or_pending(onion)
            or self._state.has_unrevoked_live_context(onion)
            or self._state.has_live_reconnect_grace(onion)
            or self._state.is_retunneling(onion)
            or self._state.has_outbound_attempt(onion)
            or self._state.has_scheduled_auto_reconnect(onion)
        )

    def dismiss_live_context(
        self, onion: str, cancel_pending: bool = False
    ) -> tuple[MessageOperationReason | None, int]:
        """Delegates exact ended-context destruction to its atomic lifecycle owner."""
        return self._removal.dismiss(onion, cancel_pending)

    def has_drop_tunnel(self, onion: str) -> bool:
        """
        Checks whether a peer currently has one cached drop tunnel.

        Args:
            onion (str): The strict onion identity.

        Returns:
            bool: True if a cached drop tunnel exists.
        """
        return self._state.has_drop_tunnel(onion)

    def add_ui_focus(self, onion: str) -> None:
        """
        Registers that a connected UI client is actively focused on a peer.

        Args:
            onion (str): The strict onion identity.

        Returns:
            None
        """
        self._state.add_ui_focus(onion)

    def remove_ui_focus(self, onion: str) -> None:
        """
        Removes one UI focus reference from a peer.

        Args:
            onion (str): The strict onion identity.

        Returns:
            None
        """
        self._state.remove_ui_focus(onion)

    def on_live_consumer_available(self) -> None:
        """
        Re-evaluates pending inbound live flows when an interactive consumer appears.

        Args:
            None

        Returns:
            None
        """
        self._controller.on_live_consumer_available()

    def force_fallback(
        self, target: str, msg_ids: Optional[list[str]] = None
    ) -> Tuple[bool, EventType, Dict[str, JsonValue]]:
        """
        Forces all unacknowledged outgoing live messages to the drop queue.

        Args:
            target (str): The target alias or onion address.
            msg_ids (Optional[list[str]]): Selected logical IDs, or all.

        Returns:
            Tuple[bool, EventType, Dict[str, JsonValue]]: A success flag, strict event type, and payload.
        """
        return self._router.force_fallback(target, msg_ids)

    def send_message(
        self,
        target: str,
        msg: str,
        msg_id: str,
        local_result: Optional[Callable[[IpcEvent], None]] = None,
    ) -> None:
        """
        Sends a live chat message and buffers it for ACK verification.

        Args:
            target (str): The target alias or onion.
            msg (str): The message content.
            msg_id (str): The unique message identifier.
            local_result: Optional requesting-client callback for local admission outcomes.

        Returns:
            None
        """
        if local_result is None:
            self._router.send_message(target, msg, msg_id)
        else:
            self._router.send_message(target, msg, msg_id, local_result)

    def begin_voice(
        self, target: str, delivery: Delivery, msg_id: str, codec: str
    ) -> None:
        """Begins one logical Voice transfer.

        Args:
            target (str): Peer alias or onion.
            delivery (Delivery): Requested delivery semantics.
            msg_id (str): Stable logical identity.
            codec (str): Codec identifier.

        Returns:
            None
        """
        self._router.begin_voice(target, delivery, msg_id, codec)

    def append_voice(self, msg_id: str, offset: int, data: str) -> None:
        """Appends one local Voice chunk.

        Args:
            msg_id (str): Stable identity.
            offset (int): Exact byte offset.
            data (str): Base64 chunk.

        Returns:
            None
        """
        self._router.append_voice(msg_id, offset, data)

    def finalize_voice(self, msg_id: str, duration_ms: Optional[int]) -> None:
        """Finalizes one local Voice turn.

        Args:
            msg_id (str): Stable identity.
            duration_ms (Optional[int]): Optional duration metadata.

        Returns:
            None
        """
        self._router.finalize_voice(msg_id, duration_ms)

    def release_consumed_voice(self, onion: str, msg_ids: List[str]) -> None:
        """Releases consumed inbound LIVE Voice payloads.

        Args:
            onion (str): The onion input.
            msg_ids (List[str]): The msg ids input.

        Returns:
            None
        """
        self._router.release_consumed_voice(onion, msg_ids)

    def voice_context(self, onion: str, msg_id: str, direction: str) -> int | None:
        """Returns immutable recording provenance for protected draft ownership.

        Args:
            onion (str): The onion input.
            msg_id (str): The msg id input.
            direction (str): The direction input.

        Returns:
            int | None: The resulting value.
        """
        return self._router.voice_context(onion, msg_id, direction)

    def live_context_token(self, onion: str) -> object | None:
        """Returns logical ownership for a restricted LIVE conversation.

        Args:
            onion (str): Stable peer identity.

        Returns:
            object | None: Active logical conversation generation.
        """
        return self._state.get_live_media_generation(onion)

    def known_live_context_generation(self, onion: str) -> Optional[int]:
        """Projects a logical context lifetime without granting active permission.

        Args:
            onion: Canonical peer.
        Returns:
            Optional[int]: Known active/recovering/retained context identity.
        """
        return self._state.known_live_context_generation(onion)

    def read_voice_chunk(
        self,
        onion: str,
        msg_id: str,
        direction: MessageDirection,
        offset: int,
        max_bytes: int,
    ) -> tuple[
        Optional[VoiceContent],
        Optional[Delivery],
        Optional[bytes],
        int,
        bool,
        Optional[MessageOperationReason],
    ]:
        """Reads one bounded retained Voice byte range.

        Args:
            onion (str): The onion input.
            msg_id (str): The msg id input.
            direction (MessageDirection): The direction input.
            offset (int): The offset input.
            max_bytes (int): The max bytes input.

        Returns:
            tuple[Optional[VoiceContent], Optional[Delivery], Optional[bytes], int, bool, Optional[MessageOperationReason]]: The resulting value.
        """
        return self._router.read_voice_chunk(
            onion, msg_id, direction, offset, max_bytes
        )

    def release_inbound_voice_item(self, onion: str, msg_id: str) -> bool:
        """Consumes one finalized inbound Voice item explicitly.

        Args:
            onion (str): The onion input.
            msg_id (str): The msg id input.

        Returns:
            bool: Whether the documented condition holds.
        """
        return self._router.release_inbound_voice_item(onion, msg_id)

    def commit_voice_draft(
        self,
        target: str,
        msg_id: str,
        delivery: Delivery | None = None,
        context_generation: int | None = None,
    ) -> bool:
        """Publishes one finalized local Voice draft after explicit Send.

        Args:
            target (str): The target input.
            msg_id (str): The msg id input.

        Returns:
            bool: Whether the documented condition holds.
        """
        return self._router.commit_voice_draft(
            target, msg_id, delivery, context_generation
        )

    def cancel_voice_draft(self, target: str, msg_id: str) -> bool:
        """Cancels one unsent local Voice draft in either delivery mode.

        Args:
            target (str): The target input.
            msg_id (str): The msg id input.

        Returns:
            bool: Whether the documented condition holds.
        """
        return self._router.cancel_voice_draft(target, msg_id)

    def finalize_interrupted_voice(self, onion: str, msg_id: str) -> bool:
        """Delegates accepted-prefix finalization after producer revocation.

        Args:
            onion: Canonical peer.
            msg_id: Exact interrupted recording identity.
        Returns:
            bool: Whether canonical finalization is confirmed.
        """
        return self._router.finalize_interrupted_voice(onion, msg_id)

    def set_voice_capture_allocator(
        self, allocator: Callable[[str, bytes], str]
    ) -> None:
        """Installs the protected producer allocation boundary.

        Args:
            allocator: Core pre-write object journal adapter.
        Returns:
            None
        """
        self._router.set_voice_capture_allocator(allocator)

    def dismiss_inbound_voice(self, onion: str) -> None:
        """Releases inbound Voice payloads for a dismissed LIVE context.

        Args:
            onion (str): The onion input.

        Returns:
            None
        """
        self._router.dismiss_inbound_voice(onion)

    def cancel_pending_live_voice(
        self, onion: str, pending: list[PendingLiveRecord]
    ) -> None:
        """Releases published LIVE Voice only after exact SQL cancellation commits.

        Callers hold the domain operation barrier and revoke replay/writer claims
        first. This cleanup preserves logical receipts and unpublished drafts.
        """
        self._router.cancel_pending_live_voice(onion, pending)

    def get_active_onions(self) -> List[str]:
        """
        Returns a snapshot of all currently connected and pending onions.

        Args:
            None

        Returns:
            List[str]: Active Tor connection onions.
        """
        return self._state.get_active_onions()

    def get_relevant_live_onions(self) -> List[str]:
        """Returns every peer with canonical LIVE runtime state.

        Args:
            None

        Returns:
            List[str]: LIVE-relevant onion identities.
        """
        return self._state.get_relevant_live_onions()

    def get_active_aliases(self) -> List[str]:
        """
        Returns a snapshot of currently connected aliases.

        Args:
            None

        Returns:
            List[str]: Active connection aliases.
        """
        return [
            self._cm.require_alias_by_onion(onion)
            for onion in self._state.get_active_connections_keys()
        ]

    def get_pending_aliases(self) -> List[str]:
        """
        Returns a snapshot of aliases waiting for acceptance.

        Args:
            None

        Returns:
            List[str]: Pending connection aliases.
        """
        return [
            self._cm.require_alias_by_onion(onion)
            for onion in self._state.get_pending_connections_keys()
        ]

    def get_pending_connection_snapshots(self) -> List[PendingConnectionSnapshot]:
        """
        Returns startup-oriented pending connection snapshots.

        Args:
            None

        Returns:
            List[PendingConnectionSnapshot]: Pending connection snapshots.
        """
        return self._state.get_pending_connection_snapshots()

    def get_live_state(self, onion: str) -> SessionState:
        """
        Returns the derived live transport lifecycle state for one peer.

        Args:
            onion (str): The strict onion identity.

        Returns:
            SessionState: The derived live transport lifecycle state.
        """
        return self._state.get_live_state(onion)

    def get_last_disconnect_reason(self, onion: str) -> Optional[ConnectionReasonCode]:
        """Returns the last machine-readable disconnect reason for snapshots.

        Args:
            onion (str): The onion input.

        Returns:
            Optional[ConnectionReasonCode]: The resulting value.
        """
        return self._state.get_last_disconnect_reason(onion)

    def get_last_disconnect_actor(self, onion: str) -> Optional[ConnectionActor]:
        """Returns the last machine-readable disconnect actor for snapshots.

        Args:
            onion (str): The onion input.

        Returns:
            Optional[ConnectionActor]: The resulting value.
        """
        return self._state.get_last_disconnect_actor(onion)

    def get_session_last_activity(self, onion: str) -> Optional[float]:
        """Projects Core-observed LIVE activity for canonical root ordering.

        Args:
            onion: Canonical peer identity.
        Returns:
            Optional[float]: Last local transport activity, if retained.
        """
        return self._state.get_session_last_activity(onion)

    def get_snapshot_token(self) -> Tuple[object, ...]:
        """Returns an atomic fingerprint used to reject torn projections.

        Args:
            None

        Returns:
            Tuple[object, ...]: The resulting value.
        """
        return self._state.snapshot_token()

    @contextmanager
    def snapshot_barrier(self) -> Iterator[None]:
        """Excludes transport mutation during an aggregate snapshot attempt.

        Args:
            None

        Returns:
            Iterator[None]: Context-manager iterator owning transport state.
        """
        with self._state.snapshot_barrier():
            yield

    def get_drop_tunnel_state(self, onion: str) -> Optional[TunnelState]:
        """
        Returns the cached drop-tunnel metadata for one peer.

        Args:
            onion (str): The strict onion identity.

        Returns:
            Optional[TunnelState]: The cached tunnel metadata, if present.
        """
        return self._state.get_drop_tunnel_state(onion)

    def get_focus_count(self, onion: str) -> int:
        """
        Returns the current UI focus reference count for one peer.

        Args:
            onion (str): The strict onion identity.

        Returns:
            int: The number of UI focus references for the peer.
        """
        return self._state.get_focus_count(onion)
