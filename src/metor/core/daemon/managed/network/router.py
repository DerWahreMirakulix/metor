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
from typing import List, Tuple, Dict, Callable, Optional, TYPE_CHECKING

from metor.core.api import (
    EventType,
    IpcEvent,
    FallbackSuccessEvent,
    AckEvent,
    InboxNotificationEvent,
    JsonValue,
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

        unacked: Dict[str, Tuple[str, str]] = self._state.pop_unacked_messages(onion)

        if not unacked:
            return (
                False,
                EventType.NO_PENDING_LIVE_MSGS,
                {'alias': alias, 'onion': onion},
            )

        for msg_id, pending_msg in unacked.items():
            content, timestamp = pending_msg
            self._mm.queue_message(
                contact_onion=onion,
                direction=MessageDirection.OUT,
                msg_type=MessageType.TEXT,
                payload=content,
                status=MessageStatus.PENDING,
                msg_id=msg_id,
                timestamp=timestamp,
            )
            self._hm.log_event(
                HistoryEvent.QUEUED,
                onion,
                actor=HistoryActor.LOCAL,
                detail_code=HistoryReasonCode.MANUAL_FALLBACK_TO_DROP,
            )

        self._broadcast(
            FallbackSuccessEvent(
                alias=alias,
                onion=onion,
                count=len(unacked),
                msg_ids=list(unacked.keys()),
            )
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
        Sends a live chat message formatted in JSON and buffers it for ACK verification.

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

        conn: Optional[socket.socket] = self._state.get_connection(onion)

        if not conn:
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
                    FallbackSuccessEvent(
                        alias=alias,
                        onion=onion,
                        count=1,
                        msg_ids=[msg_id],
                    )
                )
            return

        try:
            timestamp: str = datetime.now(timezone.utc).isoformat()
            self._state.add_unacked_message(onion, msg_id, msg, timestamp)
            envelope: Dict[str, JsonValue] = {
                'id': msg_id,
                'timestamp': timestamp,
                'text': msg,
            }
            envelope_str: str = json.dumps(envelope)
            b64_msg: str = base64.b64encode(envelope_str.encode('utf-8')).decode(
                'utf-8'
            )

            conn.sendall(f'{TorCommand.MSG.value} {msg_id} {b64_msg}\n'.encode('utf-8'))
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
        self._broadcast(AckEvent(msg_id=msg_id, timestamp=timestamp))

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
