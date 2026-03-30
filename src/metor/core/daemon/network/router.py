"""
Module responsible for routing application-layer messages.
Handles RAM buffering, Drop & Go fallback conversion, and parsing of incoming payloads.
"""

import socket
import base64
from typing import List, Tuple, Dict, Any, Callable, Optional

from metor.core.api import (
    IpcEvent,
    InboxDataEvent,
    MsgFallbackToDropEvent,
    AckEvent,
    RemoteMsgEvent,
    InboxNotificationEvent,
    TransCode,
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
    Settings,
    SettingKey,
)

# Local Package Imports
from metor.core.daemon.network.state import StateTracker
from metor.core.daemon.network.stream import TcpStreamReader


class MessageRouter:
    """Routes messages between the network stream, local database, and UI."""

    def __init__(
        self,
        cm: ContactManager,
        hm: HistoryManager,
        mm: MessageManager,
        state: StateTracker,
        broadcast_callback: Callable[[IpcEvent], None],
        has_clients_callback: Callable[[], bool],
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

        Returns:
            None
        """
        self._cm: ContactManager = cm
        self._hm: HistoryManager = hm
        self._mm: MessageManager = mm
        self._state: StateTracker = state
        self._broadcast: Callable[[IpcEvent], None] = broadcast_callback
        self._has_clients_callback: Callable[[], bool] = has_clients_callback

    def flush_ram_buffer(self, onion: str) -> None:
        """
        Flushes the headless RAM buffer to the UI and fires pending Tor ACKs.

        Args:
            onion (str): The target onion to flush.

        Returns:
            None
        """
        buffered_msgs: List[Tuple[str, str]] = self._state.pop_ram_buffer(onion)
        conn: Optional[socket.socket] = self._state.get_connection(onion)

        if not buffered_msgs or not conn:
            return

        alias: Optional[str] = self._cm.get_alias_by_onion(onion)
        messages_data: List[Dict[str, Any]] = [
            {'id': msg_id, 'payload': content, 'type': 'text', 'timestamp': ''}
            for msg_id, content in buffered_msgs
        ]

        self._broadcast(
            InboxDataEvent(alias=alias, messages=messages_data, is_live_flush=True)
        )

        for msg_id, _ in buffered_msgs:
            try:
                conn.sendall(f'{TorCommand.ACK.value} {msg_id}\n'.encode('utf-8'))
            except Exception:
                pass

    def force_fallback(self, target: str) -> Tuple[bool, TransCode, Dict[str, Any]]:
        """
        Forces all unacknowledged outgoing live messages to the drop queue.

        Args:
            target (str): The target alias or onion address.

        Returns:
            Tuple[bool, TransCode, Dict[str, Any]]: A success flag, response code, and params.
        """
        alias, onion, exists = self._cm.resolve_target(target)
        if not exists or not onion:
            return False, TransCode.PEER_NOT_FOUND, {'target': target}

        unacked: Dict[str, str] = self._state.pop_unacked_messages(onion)

        if not unacked:
            # We intentionally don't resolve the alias since it is dynamically inserted in the UI
            return False, TransCode.NO_PENDING_LIVE_MSGS, {'alias': alias}

        for _, content in unacked.items():
            self._mm.queue_message(
                onion,
                MessageDirection.OUT,
                MessageType.TEXT,
                content,
                MessageStatus.PENDING,
            )
            self._hm.log_event(
                HistoryEvent.ASYNC_QUEUED, onion, 'Manual fallback to drop'
            )

        self._broadcast(MsgFallbackToDropEvent(msg_ids=list(unacked.keys())))

        # We intentionally don't resolve the alias since it is dynamically inserted in the UI
        return True, TransCode.FALLBACK_SUCCESS, {'alias': alias, 'count': len(unacked)}

    def send_message(self, target: str, msg: str, msg_id: str) -> None:
        """
        Sends a live chat message and buffers it for ACK verification.

        Args:
            target (str): The target alias or onion.
            msg (str): The message content.
            msg_id (str): The unique message identifier.

        Returns:
            None
        """
        alias, onion, exists = self._cm.resolve_target(target)
        if not exists or not onion:
            return

        conn: Optional[socket.socket] = self._state.get_connection(onion)

        if not conn:
            if Settings.get(SettingKey.FALLBACK_TO_DROP):
                self._mm.queue_message(
                    onion,
                    MessageDirection.OUT,
                    MessageType.TEXT,
                    msg,
                    MessageStatus.PENDING,
                )
                self._hm.log_event(
                    HistoryEvent.ASYNC_QUEUED, onion, 'Auto fallback to drop'
                )
                self._broadcast(MsgFallbackToDropEvent(msg_ids=[msg_id]))
            return

        self._state.add_unacked_message(onion, msg_id, msg)

        try:
            b64_msg: str = base64.b64encode(msg.encode('utf-8')).decode('utf-8')
            conn.sendall(f'{TorCommand.MSG.value} {msg_id} {b64_msg}\n'.encode('utf-8'))
        except Exception:
            pass

    def process_incoming_msg(
        self, conn: socket.socket, onion: str, msg_id: str, content: str
    ) -> bool:
        """
        Processes an incoming live message, routing it to the UI or RAM buffer.

        Args:
            conn (socket.socket): The active socket connection.
            onion (str): The peer's onion identity.
            msg_id (str): The message ID.
            content (str): The decoded message text.

        Returns:
            bool: True if the connection should be terminated due to buffer overflow.
        """
        alias: Optional[str] = self._cm.get_alias_by_onion(onion)

        if self._has_clients_callback():
            try:
                conn.sendall(f'{TorCommand.ACK.value} {msg_id}\n'.encode('utf-8'))
                self._broadcast(RemoteMsgEvent(alias=alias or onion, text=content))
            except Exception:
                pass
            return False
        else:
            buffer_size: int = self._state.push_ram_buffer(onion, msg_id, content)
            max_limit: int = Settings.get(SettingKey.MAX_UNSEEN_LIVE_MSGS)
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
        Parses inbound Drop & Go offline messages efficiently.

        Args:
            conn (socket.socket): The active socket connection.
            stream (TcpStreamReader): The constrained byte stream.
            onion (str): The peer's onion identity.

        Returns:
            None
        """
        if not Settings.get(SettingKey.ALLOW_DROPS):
            try:
                conn.close()
            except Exception:
                pass
            return

        try:
            while True:
                msg: Optional[str] = stream.read_line()
                if not msg:
                    break

                if msg.startswith(f'{TorCommand.DROP.value} '):
                    parts: List[str] = msg.split(' ', 2)
                    if len(parts) == 3:
                        msg_id: str = parts[1]
                        content: str = base64.b64decode(parts[2]).decode('utf-8')

                        is_ephemeral: bool = Settings.get(SettingKey.EPHEMERAL_MESSAGES)
                        status: MessageStatus = (
                            MessageStatus.READ if is_ephemeral else MessageStatus.UNREAD
                        )

                        self._mm.queue_message(
                            onion,
                            MessageDirection.IN,
                            MessageType.TEXT,
                            content,
                            status,
                        )

                        self._hm.log_event(HistoryEvent.ASYNC_RECEIVED, onion)
                        conn.sendall(
                            f'{TorCommand.ACK.value} {msg_id}\n'.encode('utf-8')
                        )

                        alias: Optional[str] = self._cm.get_alias_by_onion(onion)
                        self._broadcast(
                            InboxNotificationEvent(
                                alias=alias,
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
