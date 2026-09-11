"""Drop queue selection, delivery policy, and acknowledgement finalization."""

import base64
import json
import socket
import threading
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Tuple

from metor.core.api import (
    AckEvent,
    ContentType,
    DropFailedEvent,
    IpcEvent,
    JsonValue,
    is_valid_message_id,
)
from metor.core.daemon.managed.models import PrimaryTransport, TorCommand
from metor.data import (
    HistoryActor,
    HistoryEvent,
    HistoryManager,
    MessageManager,
    MessageStatus,
    SettingKey,
)
from metor.data.blob import BlobLifecycle, BlobStore
from metor.utils import Constants

# Local Package Imports
from ..network import StateTracker, TcpStreamReader
from .tunnel import DropTunnelManager

if TYPE_CHECKING:
    from metor.data.profile import Config

OutboxRow = Tuple[int, str, str, str, str, str]


def parse_reject_reason(reject_line: Optional[str]) -> Optional[str]:
    """Extracts an optional reason from one peer rejection frame.

    Args:
        reject_line (Optional[str]): The raw newline-delimited rejection frame.

    Returns:
        Optional[str]: The machine-readable rejection reason, if present.
    """
    if reject_line is None:
        return None
    parts: list[str] = reject_line.strip().split()
    return parts[1] if len(parts) >= 2 else None


def is_expected_ack_line(msg_id: str, ack_line: Optional[str]) -> bool:
    """Validates one ACK frame against the expected message identifier.

    Args:
        msg_id (str): The logical message identifier awaiting confirmation.
        ack_line (Optional[str]): The raw newline-delimited ACK frame.

    Returns:
        bool: True if the ACK frame is well-formed and matches the message ID.
    """
    if ack_line is None:
        return False
    parts: list[str] = ack_line.strip().split()
    return len(parts) == 2 and parts[0] == TorCommand.ACK.value and parts[1] == msg_id


def build_drop_message(payload: str, msg_id: str, timestamp: str) -> str:
    """Builds one newline-delimited Base64 drop envelope.

    Args:
        payload (str): The message content.
        msg_id (str): The stable message identifier.
        timestamp (str): The recorded message timestamp.

    Returns:
        str: The encoded Tor DROP command line.
    """
    if not is_valid_message_id(msg_id):
        raise ValueError('Invalid message ID.')
    envelope: Dict[str, JsonValue] = {
        'id': msg_id,
        'timestamp': timestamp,
        'text': payload,
    }
    encoded_payload: str = base64.b64encode(
        json.dumps(envelope).encode('utf-8')
    ).decode('utf-8')
    return f'{TorCommand.DROP.value} {msg_id} {encoded_payload}\n'


class DropDelivery:
    """Owns durable pending-row delivery across session, tunnel, and direct paths."""

    def __init__(
        self,
        mm: MessageManager,
        hm: HistoryManager,
        state: StateTracker,
        tunnels: DropTunnelManager,
        broadcast_callback: Callable[[IpcEvent], None],
        stop_flag: threading.Event,
        config: 'Config',
        blob_store: Optional[BlobStore] = None,
    ) -> None:
        """Initializes drop delivery with its explicit collaborators.

        Args:
            mm (MessageManager): Pending-message persistence manager.
            hm (HistoryManager): Delivery history manager.
            state (StateTracker): Shared transport and request-correlation state.
            tunnels (DropTunnelManager): Authenticated tunnel owner.
            broadcast_callback (Callable[[IpcEvent], None]): IPC event broadcaster.
            stop_flag (threading.Event): Worker shutdown signal.
            config (Config): Profile configuration.
            blob_store (Optional[BlobStore]): Profile object store for Voice drops.

        Returns:
            None
        """
        self._mm: MessageManager = mm
        self._hm: HistoryManager = hm
        self._state: StateTracker = state
        self._tunnels: DropTunnelManager = tunnels
        self._broadcast: Callable[[IpcEvent], None] = broadcast_callback
        self._stop_flag: threading.Event = stop_flag
        self._config: 'Config' = config
        self._blobs = blob_store

    def process_pending(self) -> None:
        """Groups and attempts all currently pending drop rows.

        Args:
            None

        Returns:
            None
        """
        batches: Dict[str, List[OutboxRow]] = {}
        for row in self._mm.get_pending_outbox():
            batches.setdefault(row[1], []).append(row)
        for onion, messages in batches.items():
            self.process_batch(onion, messages)

    def process_batch(self, onion: str, messages: List[OutboxRow]) -> None:
        """Delivers one peer batch according to current transport policy.

        Args:
            onion (str): The target onion identity.
            messages (List[OutboxRow]): The grouped pending rows.

        Returns:
            None
        """
        if self._reuse_session(onion) and all(
            row[2] == ContentType.TEXT.value for row in messages
        ):
            self.send_over_session(onion, messages)
            return

        idle_timeout: float = self._config.get_float(
            SettingKey.DROP_TUNNEL_IDLE_TIMEOUT
        )
        if idle_timeout == 0.0:
            self._tunnels.close(onion)
            for row in messages:
                if self._stop_flag.is_set():
                    return
                self.send_single_drop(onion, row)
            return

        tunnel = self._tunnels.acquire(onion)
        if tunnel is None:
            self._log_tunnel_failure(onion)
            return
        conn, stream = tunnel

        try:
            conn.settimeout(self._config.get_float(SettingKey.STREAM_IDLE_TIMEOUT))
            for row in messages:
                db_id, _, content_type, payload, msg_id, timestamp = row
                try:
                    early_ack = self._send_drop_row(conn, stream, row)
                    self._tunnels.touch(onion, conn, stream)
                    ack_line: Optional[str] = early_ack or stream.read_line()
                    if self._handle_rejection(onion, msg_id, ack_line):
                        self._tunnels.close(onion)
                        break
                    if not is_expected_ack_line(msg_id, ack_line):
                        raise ConnectionError('Tunnel dropped or invalid ACK received.')
                    self._finalize_delivery(
                        db_id,
                        onion,
                        content_type,
                        payload,
                        msg_id,
                        timestamp,
                        transport='tunnel',
                    )
                except Exception as exc:
                    self._log_delivery_failure(onion, str(exc))
                    self._tunnels.close(onion)
                    break

            if (
                self._state.get_primary_transport(
                    onion,
                    standby_drop_allowed=self.is_drop_standby_allowed(),
                )
                is PrimaryTransport.SESSION
                and not self.is_drop_standby_allowed()
            ):
                self._tunnels.close(onion)
        except Exception as exc:
            self._log_delivery_failure(onion, str(exc))
            self._tunnels.close(onion)

    def send_single_drop(self, onion: str, row: OutboxRow) -> None:
        """Delivers exactly one row over a short-lived direct tunnel.

        Args:
            onion (str): The target onion identity.
            row (OutboxRow): The queued outbox row.

        Returns:
            None
        """
        if self._reuse_session(onion) and row[2] == ContentType.TEXT.value:
            self.send_over_session(onion, [row])
            return

        tunnel = self._tunnels.establish(onion)
        if tunnel is None:
            self._log_tunnel_failure(onion)
            return
        conn, stream = tunnel
        db_id, _, content_type, payload, msg_id, timestamp = row

        try:
            conn.settimeout(self._config.get_float(SettingKey.STREAM_IDLE_TIMEOUT))
            early_ack = self._send_drop_row(conn, stream, row)
            ack_line: Optional[str] = early_ack or stream.read_line()
            if self._handle_rejection(onion, msg_id, ack_line):
                return
            if not is_expected_ack_line(msg_id, ack_line):
                raise ConnectionError('Tunnel dropped or invalid ACK received.')
            self._finalize_delivery(
                db_id,
                onion,
                content_type,
                payload,
                msg_id,
                timestamp,
                transport='direct',
            )
        except Exception as exc:
            self._log_delivery_failure(onion, str(exc))
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def send_over_session(self, onion: str, messages: List[OutboxRow]) -> None:
        """Writes pending drops to an active session for receiver-owned ACKs.

        Args:
            onion (str): The target onion identity.
            messages (List[OutboxRow]): The grouped pending rows.

        Returns:
            None
        """
        conn: Optional[socket.socket] = self._state.get_connection(onion)
        if conn is None:
            return
        for row in messages:
            if self._stop_flag.is_set():
                return
            _, _, _, payload, msg_id, timestamp = row
            try:
                conn.sendall(
                    build_drop_message(payload, msg_id, timestamp).encode('utf-8')
                )
            except Exception:
                return

    def _send_drop_row(
        self,
        conn: socket.socket,
        stream: TcpStreamReader,
        row: OutboxRow,
    ) -> Optional[str]:
        """Sends one text or bounded resumable Voice DROP, leaving final ACK unread."""
        _, _, content_type, payload, msg_id, timestamp = row
        if content_type == ContentType.TEXT.value:
            conn.sendall(build_drop_message(payload, msg_id, timestamp).encode('utf-8'))
            return None
        if content_type != ContentType.VOICE.value or self._blobs is None:
            raise ValueError('Unsupported DROP content type.')
        metadata = json.loads(payload)
        if not isinstance(metadata, dict):
            raise ValueError('Invalid Voice DROP metadata.')
        blob_id = str(metadata['blob_id'])
        codec = str(metadata['codec'])
        data = self._blobs.read(blob_id, BlobLifecycle.PERSISTENT)
        begin: Dict[str, JsonValue] = {
            'id': msg_id,
            'codec': codec,
            'timestamp': timestamp,
        }
        conn.sendall(self._voice_frame(TorCommand.DROP_VOICE_BEGIN, begin))
        resume_line = stream.read_line()
        if resume_line is not None and is_expected_ack_line(msg_id, resume_line):
            return resume_line
        offset = self._parse_voice_offset(msg_id, resume_line, len(data))
        while offset < len(data):
            previous_offset = offset
            chunk = data[offset : offset + Constants.VOICE_CHUNK_MAX_BYTES]
            conn.sendall(
                self._voice_frame(
                    TorCommand.DROP_VOICE_CHUNK,
                    {
                        'id': msg_id,
                        'offset': offset,
                        'data': base64.b64encode(chunk).decode('ascii'),
                    },
                )
            )
            offset = self._parse_voice_offset(msg_id, stream.read_line(), len(data))
            if offset <= previous_offset:
                raise ConnectionError('Voice DROP acknowledgement did not advance.')
        conn.sendall(
            self._voice_frame(
                TorCommand.DROP_VOICE_END,
                {'id': msg_id, 'size': len(data)},
            )
        )
        return None

    @staticmethod
    def _voice_frame(command: TorCommand, payload: Dict[str, JsonValue]) -> bytes:
        """Encodes one bounded Voice DROP protocol frame."""
        encoded = base64.b64encode(
            json.dumps(payload, separators=(',', ':')).encode('utf-8')
        ).decode('ascii')
        return f'{command.value} {encoded}\n'.encode('ascii')

    @staticmethod
    def _parse_voice_offset(msg_id: str, line: Optional[str], maximum: int) -> int:
        """Validates one exact monotonic Voice resume acknowledgement."""
        if line is None:
            raise ConnectionError('Voice DROP acknowledgement missing.')
        parts = line.split()
        if (
            len(parts) != 3
            or parts[0] != TorCommand.VOICE_ACK.value
            or parts[1] != msg_id
        ):
            raise ConnectionError('Voice DROP acknowledgement invalid.')
        offset = int(parts[2])
        if offset < 0 or offset > maximum:
            raise ConnectionError('Voice DROP acknowledgement offset invalid.')
        return offset

    def is_drop_standby_allowed(self) -> bool:
        """Checks whether cached drop standby may coexist with live state.

        Args:
            None

        Returns:
            bool: True if drop standby is enabled.
        """
        return self._config.get_bool(SettingKey.ALLOW_DROP_STANDBY_ON_LIVE)

    def _reuse_session(self, onion: str) -> bool:
        """Checks whether current policy routes drops over an active session.

        Args:
            onion (str): The target onion identity.

        Returns:
            bool: True when session reuse applies.
        """
        return self._config.get_bool(
            SettingKey.REUSE_LIVE_FOR_DROPS
        ) and self._state.is_live_active(onion)

    def _handle_rejection(
        self, onion: str, msg_id: str, response_line: Optional[str]
    ) -> bool:
        """Projects a peer rejection while leaving the durable row pending.

        Args:
            onion (str): The target onion identity.
            msg_id (str): The rejected message identifier.
            response_line (Optional[str]): The peer response frame.

        Returns:
            bool: True when the response was a rejection.
        """
        if response_line is None or not response_line.strip().startswith(
            TorCommand.REJECT.value
        ):
            return False
        reason: Optional[str] = parse_reject_reason(response_line)
        self._broadcast(DropFailedEvent(msg_id=msg_id, reason=reason))
        self._log_delivery_failure(
            onion,
            'Drop rejected by peer: ' + reason if reason else 'Drop rejected by peer.',
        )
        return True

    def _finalize_delivery(
        self,
        db_id: int,
        onion: str,
        content_type: str,
        payload: str,
        msg_id: str,
        timestamp: str,
        transport: str,
    ) -> None:
        """Marks one acknowledged drop delivered and emits its correlated ACK.

        Args:
            db_id (int): The durable message row identifier.
            onion (str): The target onion identity.
            content_type (str): Stored typed content discriminator.
            payload (str): Stored text or Voice metadata.
            msg_id (str): The acknowledged message identifier.
            timestamp (str): The original message timestamp.
            transport (str): The transport ledger value.

        Returns:
            None
        """
        self._mm.update_message_status(db_id, MessageStatus.DELIVERED)
        if (
            content_type == ContentType.VOICE.value
            and self._blobs is not None
            and not self._mm.has_drop_payload(onion, msg_id)
        ):
            try:
                metadata = json.loads(payload)
                if isinstance(metadata, dict):
                    self._blobs.delete(
                        str(metadata['blob_id']), BlobLifecycle.PERSISTENT
                    )
            except (KeyError, OSError, TypeError, ValueError):
                pass
        self._hm.log_event(
            HistoryEvent.SENT,
            onion,
            actor=HistoryActor.LOCAL,
            transport=transport,
        )
        self._broadcast(
            AckEvent(
                msg_id=msg_id,
                timestamp=timestamp,
                request_id=self._state.pop_message_request_id(msg_id),
            )
        )

    def _log_tunnel_failure(self, onion: str) -> None:
        """Records one failed Tor tunnel establishment.

        Args:
            onion (str): The target onion identity.

        Returns:
            None
        """
        self._hm.log_event(
            HistoryEvent.TUNNEL_FAILED,
            onion,
            actor=HistoryActor.SYSTEM,
            detail_text='Failed to build Tor circuit',
        )

    def _log_delivery_failure(self, onion: str, detail: str) -> None:
        """Records one failed drop delivery attempt.

        Args:
            onion (str): The target onion identity.
            detail (str): The failure detail.

        Returns:
            None
        """
        self._hm.log_event(
            HistoryEvent.FAILED,
            onion,
            actor=HistoryActor.SYSTEM,
            detail_text=detail,
        )
