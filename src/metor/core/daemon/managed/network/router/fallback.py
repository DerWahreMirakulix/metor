"""Durable recovery and live-to-drop fallback for routed messages."""

import socket
import threading
from typing import TYPE_CHECKING, Callable, Dict, Optional, Tuple

from metor.core.api import (
    EventType,
    FallbackSuccessEvent,
    IpcEvent,
    JsonValue,
    MessageOperationReason,
    RuntimeStateChangedEvent,
)
from metor.core.daemon.managed.models import TorCommand
from metor.data import (
    HistoryActor,
    HistoryEvent,
    HistoryReasonCode,
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
        transition_lock: Optional[threading.RLock] = None,
        promote_voice_callback: Optional[Callable[[list[str], str], None]] = None,
        purge_fence: Optional[threading.Event] = None,
    ) -> None:
        """Initializes fallback routing with its explicit collaborators.

        Args:
            cm (ContactManager): Address book manager.
            hm (HistoryManager): Event history manager.
            mm (MessageManager): Message persistence manager.
            state (StateTracker): Pending-message and connection state.
            broadcast_callback (Callable[[IpcEvent], None]): IPC event broadcaster.
            config (Config): Profile configuration.
            transition_lock (Optional[threading.RLock]): Shared message transition lock.
            promote_voice_callback (Optional[Callable]): Blob ownership transition.
            purge_fence (Optional[threading.Event]): Destructive lifecycle fence.

        Returns:
            None
        """
        self._cm: 'ContactManager' = cm
        self._hm: 'HistoryManager' = hm
        self._mm: 'MessageManager' = mm
        self._state: StateTracker = state
        self._broadcast: Callable[[IpcEvent], None] = broadcast_callback
        self._config: 'Config' = config
        self._transition_lock = transition_lock or threading.RLock()
        self._promote_voice = promote_voice_callback or (lambda _msg_ids, _peer: None)
        self._purge_fence = purge_fence or threading.Event()

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
        state_messages: Dict[str, Tuple[str, str]] = self._state.get_unacked_messages(
            onion
        )

        for record in self._mm.get_pending_live_outbox(onion):
            if record.content_type != 'text':
                continue
            if record.msg_id not in state_messages:
                self._state.add_unacked_message(
                    onion, record.msg_id, record.payload, record.timestamp
                )
            pending_messages.append((record.msg_id, record.payload, record.timestamp))

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
        with self._transition_lock:
            if self._purge_fence.is_set():
                return {}
            records = self._mm.promote_pending_live_to_drop(onion)
            if not records:
                return {}
            self._state.invalidate_live_generations(
                onion, [record.msg_id for record in records]
            )
            self._promote_voice([record.msg_id for record in records], onion)
            unacked: Dict[str, Tuple[str, str]] = {
                record.msg_id: (record.payload, record.timestamp) for record in records
            }
            for record in records:
                self._state.remove_unacked_message(onion, record.msg_id)
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
            self._broadcast(RuntimeStateChangedEvent(scope='messages', onion=onion))
        return unacked

    def replay_unacked_messages(self, onion: str) -> list[str]:
        """Replays still-pending live messages over the current active socket.

        Args:
            onion (str): The peer onion identity.

        Returns:
            list[str]: The message IDs replayed successfully.
        """
        replayed_msg_ids: list[str] = []
        with self._transition_lock:
            if self._purge_fence.is_set():
                return []
            conn: Optional[socket.socket] = self._state.get_connection(onion)
            if conn is None:
                return []
            frames = self._get_pending_live_messages(onion)
            for msg_id, content, timestamp in frames:
                if self._purge_fence.is_set():
                    break
                generation = self._state.get_live_generation(onion, msg_id)
                if generation is None:
                    continue
                expected_generation = generation

                def claim(
                    peer: str = onion,
                    identity: str = msg_id,
                    expected: int = expected_generation,
                ) -> bool:
                    with self._transition_lock:
                        return (
                            not self._purge_fence.is_set()
                            and self._state.is_live_generation(peer, identity, expected)
                        )

                try:
                    self._state.send_frame(
                        conn,
                        build_message_frame(
                            TorCommand.MSG,
                            msg_id,
                            content,
                            timestamp,
                        ).encode('utf-8'),
                        claim,
                    )
                except Exception:
                    break
                replayed_msg_ids.append(msg_id)
        return replayed_msg_ids

    def force_fallback(
        self, target: str, msg_ids: Optional[list[str]] = None
    ) -> Tuple[bool, EventType, Dict[str, JsonValue]]:
        """Forces all unacknowledged outgoing live messages to the drop queue.

        Args:
            target (str): The target alias or onion address.
            msg_ids (Optional[list[str]]): Selected IDs, or all pending IDs.

        Returns:
            Tuple[bool, EventType, Dict[str, JsonValue]]: The operation result.
        """
        resolved: Optional[Tuple[str, str]] = self._cm.resolve_target(target)
        if not resolved:
            return False, EventType.PEER_NOT_FOUND, {'target': target}
        alias, onion = resolved
        with self._transition_lock:
            if self._purge_fence.is_set():
                return False, EventType.FALLBACK_REJECTED, {'target': target}
            try:
                records = self._mm.promote_pending_live_to_drop(onion, msg_ids)
            except Exception:
                return (
                    False,
                    EventType.FALLBACK_REJECTED,
                    {
                        'alias': alias,
                        'onion': onion,
                        'msg_ids': list(msg_ids or []),
                        'reason': MessageOperationReason.PERSISTENCE_FAILED.value,
                    },
                )
            if records is None:
                selected_ids: list[JsonValue] = list(msg_ids or [])
                return (
                    False,
                    EventType.FALLBACK_REJECTED,
                    {
                        'alias': alias,
                        'onion': onion,
                        'msg_ids': selected_ids,
                        'reason': MessageOperationReason.INVALID_SELECTION.value,
                    },
                )
            self._state.invalidate_live_generations(
                onion, [record.msg_id for record in records]
            )
            try:
                self._promote_voice([record.msg_id for record in records], onion)
            except Exception:
                return (
                    False,
                    EventType.FALLBACK_REJECTED,
                    {
                        'alias': alias,
                        'onion': onion,
                        'msg_ids': list(msg_ids or []),
                        'reason': MessageOperationReason.PERSISTENCE_FAILED.value,
                    },
                )
            for record in records:
                self._state.remove_unacked_message(onion, record.msg_id)
                self._hm.log_event(
                    HistoryEvent.QUEUED,
                    onion,
                    actor=HistoryActor.LOCAL,
                    detail_code=HistoryReasonCode.MANUAL_FALLBACK_TO_DROP,
                )
        if not records:
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
                'count': len(records),
                'msg_ids': [record.msg_id for record in records],
            },
        )

    def finalize_pending_live_messages(self) -> list[str]:
        """Converts remaining durable pending live messages into drops on shutdown.

        Args:
            None

        Returns:
            None
        """
        if self._purge_fence.is_set() or not self._config.get_bool(
            SettingKey.FALLBACK_TO_DROP
        ):
            return []

        pending_onions: set[str] = set(self._state.get_unacked_onions())
        for record in self._mm.get_pending_live_outbox():
            pending_onions.add(record.peer_onion)

        promoted: list[str] = []
        for onion in pending_onions:
            alias: str = self._cm.ensure_alias_for_onion(onion) or onion
            promoted.extend(
                self.convert_unacked_messages_to_drop(alias, onion, emit_event=False)
            )
        return promoted
