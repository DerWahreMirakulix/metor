"""Durable recovery and live-to-drop fallback for routed messages."""

import socket
from typing import TYPE_CHECKING, Callable, Dict, Optional, Tuple

from metor.core.api import (
    ContentType,
    Delivery,
    EventType,
    FallbackSuccessEvent,
    IpcEvent,
    JsonValue,
    get_current_request_id,
)
from metor.core.daemon.managed.models import TorCommand
from metor.data import (
    HistoryActor,
    HistoryEvent,
    HistoryReasonCode,
    MessageDirection,
    MessageStatus,
    SettingKey,
)

# Local Package Imports
from ..state import StateTracker
from .codec import build_message_frame

if TYPE_CHECKING:
    from metor.data import ContactManager, HistoryManager, MessageManager
    from metor.data.profile import Config


class FallbackRouter:
    """Owns durable recovery, replay, and conversion of outbound live messages."""

    def __init__(
        self,
        cm: 'ContactManager',
        hm: 'HistoryManager',
        mm: 'MessageManager',
        state: StateTracker,
        broadcast_callback: Callable[[IpcEvent], None],
        config: 'Config',
    ) -> None:
        """Initializes fallback routing with its explicit collaborators.

        Args:
            cm (ContactManager): Address book manager.
            hm (HistoryManager): Event history manager.
            mm (MessageManager): Message persistence manager.
            state (StateTracker): Pending-message and connection state.
            broadcast_callback (Callable[[IpcEvent], None]): IPC event broadcaster.
            config (Config): Profile configuration.

        Returns:
            None
        """
        self._cm: 'ContactManager' = cm
        self._hm: 'HistoryManager' = hm
        self._mm: 'MessageManager' = mm
        self._state: StateTracker = state
        self._broadcast: Callable[[IpcEvent], None] = broadcast_callback
        self._config: 'Config' = config

    def _get_pending_live_messages(
        self,
        onion: str,
    ) -> list[tuple[str, str, str]]:
        """Returns ordered pending live messages from durable and in-memory state.

        Args:
            onion (str): The peer onion identity.

        Returns:
            list[tuple[str, str, str]]: Message ID, payload, and timestamp tuples.
        """
        pending_messages: list[tuple[str, str, str]] = []
        seen_msg_ids: set[str] = set()
        state_messages: Dict[str, Tuple[str, str]] = self._state.get_unacked_messages(
            onion
        )

        for _, _, payload, msg_id, timestamp in self._mm.get_pending_live_outbox(onion):
            if msg_id not in state_messages:
                self._state.add_unacked_message(onion, msg_id, payload, timestamp)
            else:
                payload, timestamp = state_messages[msg_id]
            pending_messages.append((msg_id, payload, timestamp))
            seen_msg_ids.add(msg_id)

        for msg_id, pending_msg in state_messages.items():
            if msg_id not in seen_msg_ids:
                pending_messages.append((msg_id, pending_msg[0], pending_msg[1]))

        return pending_messages

    def convert_unacked_messages_to_drop(
        self,
        alias: str,
        onion: str,
        request_id: Optional[str] = None,
        emit_event: bool = True,
        history_actor: HistoryActor = HistoryActor.SYSTEM,
        history_reason_code: HistoryReasonCode = (
            HistoryReasonCode.UNACKED_LIVE_CONVERTED_TO_DROP
        ),
    ) -> Dict[str, Tuple[str, str]]:
        """Converts tracked unacknowledged live messages into pending drops.

        Args:
            alias (str): The peer alias.
            onion (str): The peer onion identity.
            request_id (Optional[str]): Optional request correlation identifier.
            emit_event (bool): Whether to emit a fallback-success event.
            history_actor (HistoryActor): The history actor for queued-drop logging.
            history_reason_code (HistoryReasonCode): The queued-drop history reason.

        Returns:
            Dict[str, Tuple[str, str]]: The converted unacknowledged messages.
        """
        unacked: Dict[str, Tuple[str, str]] = self._state.pop_unacked_messages(onion)
        for _, _, payload, msg_id, timestamp in self._mm.get_pending_live_outbox(onion):
            unacked.setdefault(msg_id, (payload, timestamp))
        if not unacked:
            return {}

        for msg_id, (content, timestamp) in unacked.items():
            self._mm.queue_message(
                contact_onion=onion,
                direction=MessageDirection.OUT,
                delivery=Delivery.DROP,
                content_type=ContentType.TEXT,
                payload=content,
                status=MessageStatus.PENDING,
                msg_id=msg_id,
                timestamp=timestamp,
            )
            self._hm.log_event(
                HistoryEvent.QUEUED,
                onion,
                actor=history_actor,
                detail_code=history_reason_code,
            )

        if emit_event:
            self._broadcast(
                FallbackSuccessEvent(
                    alias=alias,
                    onion=onion,
                    count=len(unacked),
                    msg_ids=list(unacked),
                    request_id=request_id,
                )
            )
        return unacked

    def replay_unacked_messages(self, onion: str) -> list[str]:
        """Replays still-pending live messages over the current active socket.

        Args:
            onion (str): The peer onion identity.

        Returns:
            list[str]: The message IDs replayed successfully.
        """
        conn: Optional[socket.socket] = self._state.get_connection(onion)
        if conn is None:
            return []

        replayed_msg_ids: list[str] = []
        for msg_id, content, timestamp in self._get_pending_live_messages(onion):
            try:
                conn.sendall(
                    build_message_frame(
                        TorCommand.MSG,
                        msg_id,
                        content,
                        timestamp,
                    ).encode('utf-8')
                )
            except Exception:
                break
            replayed_msg_ids.append(msg_id)
        return replayed_msg_ids

    def force_fallback(
        self, target: str
    ) -> Tuple[bool, EventType, Dict[str, JsonValue]]:
        """Forces all unacknowledged outgoing live messages to the drop queue.

        Args:
            target (str): The target alias or onion address.

        Returns:
            Tuple[bool, EventType, Dict[str, JsonValue]]: The operation result.
        """
        resolved: Optional[Tuple[str, str]] = self._cm.resolve_target(target)
        if not resolved:
            return False, EventType.PEER_NOT_FOUND, {'target': target}
        alias, onion = resolved
        unacked = self.convert_unacked_messages_to_drop(
            alias,
            onion,
            request_id=get_current_request_id(),
            history_actor=HistoryActor.LOCAL,
            history_reason_code=HistoryReasonCode.MANUAL_FALLBACK_TO_DROP,
        )
        if not unacked:
            return (
                False,
                EventType.NO_PENDING_LIVE_MSGS,
                {'alias': alias, 'onion': onion},
            )
        return (
            True,
            EventType.FALLBACK_SUCCESS,
            {
                'alias': alias,
                'onion': onion,
                'count': len(unacked),
                'msg_ids': list(unacked),
            },
        )

    def finalize_pending_live_messages(self) -> None:
        """Converts remaining durable pending live messages into drops on shutdown.

        Args:
            None

        Returns:
            None
        """
        if not self._config.get_bool(SettingKey.FALLBACK_TO_DROP):
            return

        pending_onions: set[str] = set(self._state.get_unacked_onions())
        for _, onion, _, _, _ in self._mm.get_pending_live_outbox():
            pending_onions.add(onion)

        for onion in pending_onions:
            alias: str = self._cm.ensure_alias_for_onion(onion) or onion
            self.convert_unacked_messages_to_drop(alias, onion, emit_event=False)
