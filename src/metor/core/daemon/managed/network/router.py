"""
Module responsible for routing application-layer messages.
Handles crash-safe inbound message persistence, JSON payload parsing (UUID mapping),
and Live-to-Drop fallback conversion.
"""

import binascii
import socket
import base64
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Tuple, cast

from metor.core.api import (
    AutoFallbackQueuedEvent,
    EventType,
    IpcEvent,
    FallbackSuccessEvent,
    AckEvent,
    InboxNotificationEvent,
    JsonValue,
    get_current_request_id,
)
from metor.core.daemon.managed.models import TorCommand
from metor.data import (
    ContactManager,
    HistoryActor,
    HistoryManager,
    HistoryEvent,
    HistoryReasonCode,
    MessageManager,
    MessageDirection,
    MessageType,
    MessageStatus,
    SettingKey,
)

# Local Package Imports
from metor.core.daemon.managed.network.state import StateTracker
from metor.core.daemon.managed.network.stream import TcpStreamReader

if TYPE_CHECKING:
    from metor.data.profile import Config


class MessageRouter:
    """Routes messages between the network stream, local database, and UI. Applies strict JSON mapping."""

    def __init__(
        self,
        cm: ContactManager,
        hm: HistoryManager,
        mm: MessageManager,
        state: StateTracker,
        broadcast_callback: Callable[[IpcEvent], None],
        has_clients_callback: Callable[[], bool],
        has_live_consumers_callback: Callable[[], bool],
        config: 'Config',
    ) -> None:
        """
        Initializes the MessageRouter.

        Args:
            cm (ContactManager): Address book manager.
            hm (HistoryManager): Event history manager.
            mm (MessageManager): Offline messages manager.
            state (StateTracker): The thread-safe connection state tracker.
            broadcast_callback (Callable[[IpcEvent], None]): Callback to emit IPC events.
            has_clients_callback (Callable[[], bool]): Callback to check for active UI clients.
            has_live_consumers_callback (Callable[[], bool]): Callback to check for interactive live consumers.
            config (Config): The profile configuration instance.

        Returns:
            None
        """
        self._cm: ContactManager = cm
        self._hm: HistoryManager = hm
        self._mm: MessageManager = mm
        self._state: StateTracker = state
        self._broadcast: Callable[[IpcEvent], None] = broadcast_callback
        self._has_clients_callback: Callable[[], bool] = has_clients_callback
        self._has_live_consumers_callback: Callable[[], bool] = (
            has_live_consumers_callback
        )
        self._config: 'Config' = config

    def _remember_message_request_id(
        self,
        msg_id: str,
        request_id: Optional[str],
    ) -> None:
        """
        Stores request correlation metadata when the shared state tracker supports it.

        Args:
            msg_id (str): The logical message identifier.
            request_id (Optional[str]): The originating IPC request identifier.

        Returns:
            None
        """
        remember = getattr(self._state, 'remember_message_request_id', None)
        if callable(remember):
            remember(msg_id, request_id)

    def _clear_message_request_id(self, msg_id: str) -> None:
        """
        Clears request correlation metadata when the shared state tracker supports it.

        Args:
            msg_id (str): The logical message identifier.

        Returns:
            None
        """
        clear = getattr(self._state, 'clear_message_request_id', None)
        if callable(clear):
            clear(msg_id)

    def _pop_message_request_id(self, msg_id: str) -> Optional[str]:
        """
        Retrieves request correlation metadata when the shared state tracker supports it.

        Args:
            msg_id (str): The logical message identifier.

        Returns:
            Optional[str]: The originating IPC request identifier, if tracked.
        """
        pop = getattr(self._state, 'pop_message_request_id', None)
        if callable(pop):
            return cast(Optional[str], pop(msg_id))
        return None

    @staticmethod
    def _send_live_envelope(
        conn: socket.socket,
        msg_id: str,
        msg: str,
        timestamp: str,
    ) -> None:
        """
        Sends one strict live JSON envelope over an already authenticated socket.

        Args:
            conn (socket.socket): The active live socket.
            msg_id (str): The stable logical message identifier.
            msg (str): The message payload.
            timestamp (str): The daemon-authored send timestamp.

        Returns:
            None
        """
        envelope: Dict[str, JsonValue] = {
            'id': msg_id,
            'timestamp': timestamp,
            'text': msg,
        }
        envelope_str: str = json.dumps(envelope)
        b64_msg: str = base64.b64encode(envelope_str.encode('utf-8')).decode('utf-8')
        conn.sendall(f'{TorCommand.MSG.value} {msg_id} {b64_msg}\n'.encode('utf-8'))

    def _should_defer_live_message(self, onion: str) -> bool:
        """
        Checks whether one outbound live message should stay recoverable for now.

        Args:
            onion (str): The peer onion identity.

        Returns:
            bool: True if live recovery is still plausible.
        """
        has_live_reconnect_grace = getattr(
            self._state, 'has_live_reconnect_grace', None
        )
        is_retunneling = getattr(self._state, 'is_retunneling', None)
        has_outbound_attempt = getattr(self._state, 'has_outbound_attempt', None)
        has_scheduled_auto_reconnect = getattr(
            self._state,
            'has_scheduled_auto_reconnect',
            None,
        )
        is_connected_or_pending = getattr(
            self._state,
            'is_connected_or_pending',
            None,
        )
        return (
            bool(callable(has_live_reconnect_grace) and has_live_reconnect_grace(onion))
            or bool(callable(is_retunneling) and is_retunneling(onion))
            or bool(callable(has_outbound_attempt) and has_outbound_attempt(onion))
            or bool(
                callable(has_scheduled_auto_reconnect)
                and has_scheduled_auto_reconnect(onion)
            )
            or bool(
                callable(is_connected_or_pending) and is_connected_or_pending(onion)
            )
        )

    def _queue_pending_live_message(
        self,
        onion: str,
        msg: str,
        msg_id: str,
        timestamp: str,
    ) -> None:
        """
        Persists one outbound live message until ACK or terminal fallback.

        Args:
            onion (str): The peer onion identity.
            msg (str): The message payload.
            msg_id (str): The stable logical message identifier.
            timestamp (str): The authored timestamp.

        Returns:
            None
        """
        self._mm.queue_message(
            contact_onion=onion,
            direction=MessageDirection.OUT,
            msg_type=MessageType.LIVE_TEXT,
            payload=msg,
            status=MessageStatus.PENDING,
            msg_id=msg_id,
            timestamp=timestamp,
        )
        self._state.add_unacked_message(onion, msg_id, msg, timestamp)

    def _get_pending_live_messages(
        self,
        onion: str,
    ) -> list[tuple[str, str, str]]:
        """
        Returns ordered pending live messages from durable and in-memory state.

        Args:
            onion (str): The peer onion identity.

        Returns:
            list[tuple[str, str, str]]: Message id, payload, and timestamp tuples.
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
            if msg_id in seen_msg_ids:
                continue
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
        """
        Converts tracked unacknowledged live messages into pending drops.

        Args:
            alias (str): The peer alias.
            onion (str): The peer onion identity.
            request_id (Optional[str]): Optional request correlation identifier.
            emit_event (bool): Whether to emit a fallback-success event.
            history_actor (HistoryActor): The history actor for queued-drop logging.
            history_reason_code (HistoryReasonCode): The reason code for queued-drop logging.

        Returns:
            Dict[str, Tuple[str, str]]: The converted unacknowledged messages.
        """
        unacked: Dict[str, Tuple[str, str]] = self._state.pop_unacked_messages(onion)
        for _, _, payload, msg_id, timestamp in self._mm.get_pending_live_outbox(onion):
            unacked.setdefault(msg_id, (payload, timestamp))
        if not unacked:
            return {}

        for msg_id, pending_msg in unacked.items():
            content, timestamp = pending_msg
            self._mm.queue_message(
                contact_onion=onion,
                direction=MessageDirection.OUT,
                msg_type=MessageType.DROP_TEXT,
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
                    msg_ids=list(unacked.keys()),
                    request_id=request_id,
                )
            )

        return unacked

    def replay_unacked_messages(self, onion: str) -> list[str]:
        """
        Replays still-pending live messages over the current active socket.

        Args:
            onion (str): The peer onion identity.

        Returns:
            list[str]: The message IDs that were replayed successfully.
        """
        conn: Optional[socket.socket] = self._state.get_connection(onion)
        if conn is None:
            return []

        replayed_msg_ids: list[str] = []
        for msg_id, content, timestamp in self._get_pending_live_messages(onion):
            try:
                self._send_live_envelope(conn, msg_id, content, timestamp)
            except Exception:
                break
            replayed_msg_ids.append(msg_id)

        return replayed_msg_ids

    def force_fallback(
        self, target: str
    ) -> Tuple[bool, EventType, Dict[str, JsonValue]]:
        """
        Forces all unacknowledged outgoing live messages to the drop queue.

        Args:
            target (str): The target alias or onion address.

        Returns:
            Tuple[bool, EventType, Dict[str, JsonValue]]: A success flag, strict event type, and payload.
        """
        resolved: Optional[Tuple[str, str]] = self._cm.resolve_target(target)
        if not resolved:
            return False, EventType.PEER_NOT_FOUND, {'target': target}
        alias, onion = resolved
        request_id: Optional[str] = get_current_request_id()

        unacked: Dict[str, Tuple[str, str]] = self.convert_unacked_messages_to_drop(
            alias,
            onion,
            request_id=request_id,
            emit_event=True,
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
                'msg_ids': list(unacked.keys()),
            },
        )

    def send_message(self, target: str, msg: str, msg_id: str) -> None:
        """
        Sends one live chat message or durably defers it for recovery.

        Args:
            target (str): The target alias or onion.
            msg (str): The message content.
            msg_id (str): The unique message identifier (UUID).

        Returns:
            None
        """
        resolved: Optional[Tuple[str, str]] = self._cm.resolve_target(target)
        if not resolved:
            return
        alias, onion = resolved
        request_id: Optional[str] = get_current_request_id()
        self._remember_message_request_id(msg_id, request_id)
        conn: Optional[socket.socket] = self._state.get_connection(onion)
        timestamp: str = datetime.now(timezone.utc).isoformat()

        if not conn:
            if self._should_defer_live_message(onion) or not self._config.get_bool(
                SettingKey.FALLBACK_TO_DROP
            ):
                self._queue_pending_live_message(onion, msg, msg_id, timestamp)
                return

            if self._config.get_bool(SettingKey.FALLBACK_TO_DROP):
                self._mm.queue_message(
                    contact_onion=onion,
                    direction=MessageDirection.OUT,
                    msg_type=MessageType.DROP_TEXT,
                    payload=msg,
                    status=MessageStatus.PENDING,
                    msg_id=msg_id,
                )
                self._hm.log_event(
                    HistoryEvent.QUEUED,
                    onion,
                    actor=HistoryActor.SYSTEM,
                    detail_code=HistoryReasonCode.AUTO_FALLBACK_TO_DROP,
                )
                self._broadcast(
                    AutoFallbackQueuedEvent(
                        alias=alias,
                        onion=onion,
                        msg_id=msg_id,
                        request_id=request_id,
                    )
                )
            return

        try:
            self._queue_pending_live_message(onion, msg, msg_id, timestamp)
            self._send_live_envelope(conn, msg_id, msg, timestamp)
        except Exception:
            pass

    def process_incoming_msg(
        self, conn: socket.socket, onion: str, payload_id: str, b64_payload: str
    ) -> bool:
        """
        Processes an incoming JSON-enveloped live message, persisting it durably before ACK.

        Args:
            conn (socket.socket): The active socket connection.
            onion (str): The peer's onion identity.
            payload_id (str): The Tor message routing ID (fallback).
            b64_payload (str): The Base64 encoded JSON text payload.

        Returns:
            bool: True if the connection should be terminated due to live backlog pressure.
        """
        try:
            msg_id, content, timestamp = self._decode_live_payload(
                payload_id,
                b64_payload,
            )
        except ValueError as exc:
            self._hm.log_event(
                HistoryEvent.STREAM_CORRUPTED,
                onion,
                actor=HistoryActor.SYSTEM,
                detail_text=str(exc),
            )
            return True

        alias: Optional[str] = self._cm.ensure_alias_for_onion(onion)

        if self._mm.has_inbound_message(onion, msg_id):
            try:
                conn.sendall(f'{TorCommand.ACK.value} {msg_id}\n'.encode('utf-8'))
            except Exception:
                pass
            return False

        has_clients: bool = self._has_clients_callback()
        has_live_consumers: bool = self._has_live_consumers_callback()
        unread_live_limit: int = self._config.get_int(SettingKey.MAX_UNSEEN_LIVE_MSGS)
        if unread_live_limit == 0:
            if not has_live_consumers:
                return True
        elif self._mm.get_unread_live_count(onion) >= unread_live_limit:
            return True

        queue_result = self._mm.queue_message(
            contact_onion=onion,
            direction=MessageDirection.IN,
            msg_type=MessageType.LIVE_TEXT,
            payload=content,
            status=MessageStatus.UNREAD,
            msg_id=msg_id,
            timestamp=timestamp or None,
        )

        try:
            conn.sendall(f'{TorCommand.ACK.value} {msg_id}\n'.encode('utf-8'))
        except Exception:
            pass

        if queue_result.was_duplicate:
            return False

        if alias and has_clients:
            self._broadcast(
                InboxNotificationEvent(
                    alias=alias,
                    onion=onion,
                    count=1,
                )
            )

        return False

    def _decode_live_payload(
        self,
        payload_id: str,
        b64_payload: str,
    ) -> Tuple[str, str, Optional[str]]:
        """
        Decodes one strict live JSON envelope and rejects malformed payloads.

        Args:
            payload_id (str): The transport-level fallback identifier.
            b64_payload (str): The received Base64 payload.

        Raises:
            ValueError: If the payload is not a valid live JSON envelope.

        Returns:
            Tuple[str, str, Optional[str]]: The decoded message ID, text payload,
                and optional timestamp.
        """
        try:
            raw_bytes: bytes = base64.b64decode(b64_payload, validate=True)
            raw_text: str = raw_bytes.decode('utf-8')
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ValueError('Invalid live payload encoding.') from exc

        try:
            envelope_raw: JsonValue = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError('Invalid live payload JSON.') from exc

        if not isinstance(envelope_raw, dict):
            raise ValueError('Invalid live payload envelope.')

        envelope: Dict[str, JsonValue] = envelope_raw
        text_value: JsonValue = envelope.get('text')
        if not isinstance(text_value, str):
            raise ValueError('Invalid live payload text field.')

        timestamp_value: JsonValue = envelope.get('timestamp')
        timestamp: Optional[str] = (
            str(timestamp_value) if timestamp_value is not None else None
        )
        return str(envelope.get('id', payload_id)), text_value, timestamp

    def process_incoming_ack(self, onion: str, msg_id: str) -> None:
        """
        Processes an acknowledgment for a previously sent message.

        Args:
            onion (str): The peer's onion identity.
            msg_id (str): The acknowledged message ID.

        Returns:
            None
        """
        acked_msg: Optional[Tuple[str, str]] = self._state.remove_unacked_message(
            onion, msg_id
        )
        timestamp: Optional[str] = acked_msg[1] if acked_msg else None
        self._mm.update_outbound_message_status(
            onion,
            msg_id,
            MessageStatus.DELIVERED,
        )
        request_id: Optional[str] = self._pop_message_request_id(msg_id)
        self._broadcast(
            AckEvent(
                msg_id=msg_id,
                timestamp=timestamp,
                request_id=request_id,
            )
        )

    def finalize_pending_live_messages(self) -> None:
        """
        Converts remaining durable pending live messages into drops on shutdown.

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

        ensure_alias = getattr(self._cm, 'ensure_alias_for_onion', None)
        for onion in pending_onions:
            alias: str = onion
            if callable(ensure_alias):
                resolved_alias = cast(Optional[str], ensure_alias(onion))
                if resolved_alias:
                    alias = resolved_alias
            self.convert_unacked_messages_to_drop(
                alias,
                onion,
                emit_event=False,
            )

    def _decode_async_drop_payload(
        self,
        payload_id: str,
        b64_payload: str,
    ) -> Optional[Tuple[str, str, Optional[str]]]:
        """
        Decodes one asynchronous drop payload without letting malformed data abort the stream.

        Args:
            payload_id (str): The transport-level fallback identifier.
            b64_payload (str): The received Base64 payload.

        Returns:
            Optional[Tuple[str, str, Optional[str]]]: The decoded message id, content,
                and optional timestamp, or None if the payload is invalid.
        """
        try:
            raw_bytes: bytes = base64.b64decode(b64_payload, validate=True)
            raw_text: str = raw_bytes.decode('utf-8')
        except (binascii.Error, UnicodeDecodeError):
            return None

        try:
            envelope: Dict[str, JsonValue] = json.loads(raw_text)
        except json.JSONDecodeError:
            return payload_id, raw_text, None

        timestamp_value: JsonValue = envelope.get('timestamp')
        timestamp: Optional[str] = (
            str(timestamp_value) if timestamp_value is not None else None
        )
        return (
            str(envelope.get('id', payload_id)),
            str(envelope.get('text', raw_text)),
            timestamp,
        )

    def process_async_drop(
        self, conn: socket.socket, stream: TcpStreamReader, onion: str
    ) -> None:
        """
        Parses inbound Drop & Go JSON offline messages strictly enforcing UUID Deduplication.

        Args:
            conn (socket.socket): The active socket connection.
            stream (TcpStreamReader): The constrained byte stream.
            onion (str): The peer's onion identity.

        Returns:
            None
        """
        if not self._config.get_bool(SettingKey.ALLOW_DROPS):
            try:
                conn.close()
            except Exception:
                pass
            return

        alias: Optional[str] = self._cm.ensure_alias_for_onion(onion)
        unread_drop_limit: int = self._config.get_int(SettingKey.MAX_UNSEEN_DROP_MSGS)
        try:
            while True:
                msg: Optional[str] = stream.read_line()
                if not msg:
                    break

                if msg.startswith(f'{TorCommand.DROP.value} '):
                    parts: List[str] = msg.split(' ', 2)
                    if len(parts) == 3:
                        payload_id: str = parts[1]

                        decoded_payload: Optional[Tuple[str, str, Optional[str]]] = (
                            self._decode_async_drop_payload(payload_id, parts[2])
                        )
                        if decoded_payload is None:
                            continue

                        msg_id, content, timestamp = decoded_payload

                        if self._mm.has_inbound_message(onion, msg_id):
                            conn.sendall(
                                f'{TorCommand.ACK.value} {msg_id}\n'.encode('utf-8')
                            )
                            continue

                        if (
                            unread_drop_limit != -1
                            and self._mm.get_unread_drop_count(onion)
                            >= unread_drop_limit
                        ):
                            self._hm.log_event(
                                HistoryEvent.FAILED,
                                onion,
                                actor=HistoryActor.SYSTEM,
                                detail_text='Drop backlog limit reached.',
                            )
                            break

                        queue_result = self._mm.queue_message(
                            contact_onion=onion,
                            direction=MessageDirection.IN,
                            msg_type=MessageType.DROP_TEXT,
                            payload=content,
                            status=MessageStatus.UNREAD,
                            msg_id=msg_id,
                            timestamp=timestamp,
                        )
                        conn.sendall(
                            f'{TorCommand.ACK.value} {msg_id}\n'.encode('utf-8')
                        )

                        if queue_result.was_duplicate:
                            continue

                        self._hm.log_event(
                            HistoryEvent.RECEIVED,
                            onion,
                            actor=HistoryActor.REMOTE,
                        )

                        if alias and self._has_clients_callback():
                            self._broadcast(
                                InboxNotificationEvent(
                                    alias=alias,
                                    onion=onion,
                                    count=1,
                                )
                            )
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
