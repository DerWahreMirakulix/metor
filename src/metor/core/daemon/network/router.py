"""
Module responsible for routing application-layer messages.
Handles RAM buffering, JSON Payload Parsing (UUID mapping), Drop & Go fallback conversion.
"""

import socket
import base64
import json
from datetime import datetime, timezone
from typing import List, Tuple, Dict, Callable, Optional, TYPE_CHECKING

from metor.core.api import (
    EventType,
    IpcEvent,
    InboxDataEvent,
    FallbackSuccessEvent,
    AckEvent,
    RemoteMsgEvent,
    InboxNotificationEvent,
    UnreadMessageEntry,
    JsonValue,
)
from metor.core.daemon.models import TorCommand
from metor.data import (
    ContactManager,
    HistoryManager,
    HistoryEvent,
    MessageManager,
    MessageDirection,
    MessageType,
    MessageStatus,
    SettingKey,
)

# Local Package Imports
from metor.core.daemon.network.state import StateTracker
from metor.core.daemon.network.stream import TcpStreamReader

if TYPE_CHECKING:
    from metor.data.profile.config import Config


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
        self._config: 'Config' = config

    def flush_ram_buffer(self, onion: str) -> None:
        """
        Flushes the headless RAM buffer to the UI and fires pending Tor ACKs.

        Args:
            onion (str): The target onion to flush.

        Returns:
            None
        """
        buffered_msgs: List[Tuple[str, str, str]] = self._state.pop_ram_buffer(onion)
        conn: Optional[socket.socket] = self._state.get_connection(onion)

        if not buffered_msgs or not conn:
            return

        alias: Optional[str] = self._cm.ensure_alias_for_onion(onion)
        messages_data: List[UnreadMessageEntry] = [
            UnreadMessageEntry(timestamp=timestamp, payload=content)
            for _, content, timestamp in buffered_msgs
        ]

        self._broadcast(
            InboxDataEvent(
                alias=str(alias),
                messages=messages_data,
                is_live_flush=True,
            )
        )

        for msg_id, _, _ in buffered_msgs:
            try:
                conn.sendall(f'{TorCommand.ACK.value} {msg_id}\n'.encode('utf-8'))
            except Exception:
                pass

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

        unacked: Dict[str, str] = self._state.pop_unacked_messages(onion)

        if not unacked:
            return False, EventType.NO_PENDING_LIVE_MSGS, {'alias': alias}

        for msg_id, content in unacked.items():
            self._mm.queue_message(
                contact_onion=onion,
                direction=MessageDirection.OUT,
                msg_type=MessageType.TEXT,
                payload=content,
                status=MessageStatus.PENDING,
                msg_id=msg_id,
            )
            self._hm.log_event(
                HistoryEvent.DROP_QUEUED, onion, 'Manual fallback to drop'
            )

        self._broadcast(
            FallbackSuccessEvent(
                alias=alias,
                count=len(unacked),
                msg_ids=list(unacked.keys()),
            )
        )

        return (
            True,
            EventType.FALLBACK_SUCCESS,
            {'alias': alias, 'count': len(unacked), 'msg_ids': list(unacked.keys())},
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
                    msg_type=MessageType.TEXT,
                    payload=msg,
                    status=MessageStatus.PENDING,
                    msg_id=msg_id,
                )
                self._hm.log_event(
                    HistoryEvent.DROP_QUEUED, onion, 'Auto fallback to drop'
                )
                self._broadcast(
                    FallbackSuccessEvent(
                        alias=alias,
                        count=1,
                        msg_ids=[msg_id],
                    )
                )
            return

        self._state.add_unacked_message(onion, msg_id, msg)

        try:
            timestamp: str = datetime.now(timezone.utc).isoformat()
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
        Processes an incoming JSON-enveloped live message, routing it to the UI or RAM buffer.

        Args:
            conn (socket.socket): The active socket connection.
            onion (str): The peer's onion identity.
            payload_id (str): The Tor message routing ID (fallback).
            b64_payload (str): The Base64 encoded JSON text payload.

        Returns:
            bool: True if the connection should be terminated due to buffer overflow.
        """
        alias: Optional[str] = self._cm.ensure_alias_for_onion(onion)

        msg_id: str = payload_id
        content: str = b64_payload
        timestamp: str = ''

        try:
            raw_text = base64.b64decode(b64_payload).decode('utf-8')
            envelope = json.loads(raw_text)
            msg_id = str(envelope.get('id', payload_id))
            content = str(envelope.get('text', raw_text))
            timestamp = str(envelope.get('timestamp') or '')
        except Exception:
            pass

        if self._has_clients_callback():
            try:
                conn.sendall(f'{TorCommand.ACK.value} {msg_id}\n'.encode('utf-8'))
                self._broadcast(
                    RemoteMsgEvent(alias=str(alias), text=content, timestamp=timestamp)
                )
            except Exception:
                pass
            return False
        else:
            buffer_size: int = self._state.push_ram_buffer(
                onion,
                msg_id,
                content,
                timestamp,
            )
            max_limit: int = self._config.get_int(SettingKey.MAX_UNSEEN_LIVE_MSGS)
            if buffer_size >= max_limit:
                return True
            return False

    def process_incoming_ack(self, onion: str, msg_id: str) -> None:
        """
        Processes an acknowledgment for a previously sent message.

        Args:
            onion (str): The peer's onion identity.
            msg_id (str): The acknowledged message ID.

        Returns:
            None
        """
        self._state.remove_unacked_message(onion, msg_id)
        self._broadcast(AckEvent(msg_id=msg_id))

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
        unread_count: int = 0
        is_focused: bool = self._state.is_focused_by_ui(onion)

        try:
            while True:
                msg: Optional[str] = stream.read_line()
                if not msg:
                    break

                if msg.startswith(f'{TorCommand.DROP.value} '):
                    parts: List[str] = msg.split(' ', 2)
                    if len(parts) == 3:
                        payload_id: str = parts[1]

                        try:
                            raw_text = base64.b64decode(parts[2]).decode('utf-8')
                            envelope = json.loads(raw_text)
                            msg_id = str(envelope.get('id', payload_id))
                            content = str(envelope.get('text', raw_text))
                            timestamp = (
                                str(envelope.get('timestamp'))
                                if envelope.get('timestamp')
                                else None
                            )
                        except Exception:
                            msg_id = payload_id
                            content = base64.b64decode(parts[2]).decode('utf-8')
                            timestamp = None

                        is_ephemeral: bool = self._config.get_bool(
                            SettingKey.EPHEMERAL_MESSAGES
                        )
                        should_mark_read: bool = is_ephemeral or is_focused
                        status: MessageStatus = (
                            MessageStatus.READ
                            if should_mark_read
                            else MessageStatus.UNREAD
                        )

                        self._mm.queue_message(
                            contact_onion=onion,
                            direction=MessageDirection.IN,
                            msg_type=MessageType.TEXT,
                            payload=content,
                            status=status,
                            msg_id=msg_id,
                            timestamp=timestamp,
                        )

                        self._hm.log_event(HistoryEvent.DROP_RECEIVED, onion)
                        conn.sendall(
                            f'{TorCommand.ACK.value} {msg_id}\n'.encode('utf-8')
                        )

                        if is_focused and alias:
                            self._broadcast(
                                InboxDataEvent(
                                    alias=alias,
                                    messages=[
                                        UnreadMessageEntry(
                                            timestamp=timestamp or '',
                                            payload=content,
                                        )
                                    ],
                                    is_live_flush=False,
                                )
                            )
                        else:
                            unread_count += 1
        except Exception:
            pass
        finally:
            if alias and unread_count > 0:
                self._broadcast(
                    InboxNotificationEvent(
                        alias=alias,
                        count=unread_count,
                    )
                )
            try:
                conn.close()
            except Exception:
                pass
