"""Drop queue selection, delivery policy, and acknowledgement finalization."""

import base64
import json
import socket
import threading
from functools import partial
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

# Local Package Imports
from ..network import StateTracker
from .tunnel import DropTunnelManager
from .voice import (
    DropDeliveryCancelled,
    DropResponseReader,
    VoiceDropSender,
    is_expected_voice_commit_line,
)

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
    return (
        len(parts) == 2 and parts[0] == TorCommand.DROP_ACK.value and parts[1] == msg_id
    )


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
        operation_lock: Optional[threading.RLock] = None,
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
            operation_lock (Optional[threading.RLock]): State publication barrier.

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
        self._voice_sender = VoiceDropSender(state, blob_store)
        self._operation_lock = operation_lock or threading.RLock()

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
        messages = [row for row in messages if self._is_pending(row)]
        if not messages:
            return
        if self._reuse_session(onion):
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
            with self._operation_lock:
                if any(self._is_pending(row) for row in messages):
                    self._log_tunnel_failure(onion)
            return
        conn, stream = tunnel

        try:
            conn.settimeout(self._config.get_float(SettingKey.STREAM_IDLE_TIMEOUT))
            for row in messages:
                if not self._is_pending(row):
                    continue
                db_id, _, content_type, payload, msg_id, timestamp = row
                try:
                    early_ack = self._send_drop_row(
                        conn, stream, row, partial(self._is_pending, row)
                    )
                    self._tunnels.touch(onion, conn, stream)
                    ack_line: Optional[str] = early_ack or stream.read_line()
                    if self._handle_rejection(row, ack_line):
                        self._tunnels.close(onion)
                        break
                    expected_ack = (
                        is_expected_voice_commit_line(msg_id, ack_line)
                        if content_type == ContentType.VOICE.value
                        else is_expected_ack_line(msg_id, ack_line)
                    )
                    if not expected_ack:
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
                except DropDeliveryCancelled:
                    self._tunnels.close(onion)
                    break
                except Exception:
                    if not self._is_pending(row):
                        self._tunnels.close(onion)
                        break
                    self._log_delivery_failure(onion, 'Drop delivery failed.', row=row)
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
        except Exception:
            with self._operation_lock:
                if any(self._is_pending(row) for row in messages):
                    self._log_delivery_failure(onion, 'Drop delivery failed.')
            self._tunnels.close(onion)

    def send_single_drop(self, onion: str, row: OutboxRow) -> None:
        """Delivers exactly one row over a short-lived direct tunnel.

        Args:
            onion (str): The target onion identity.
            row (OutboxRow): The queued outbox row.

        Returns:
            None
        """
        if not self._is_pending(row):
            return
        if self._reuse_session(onion):
            self.send_over_session(onion, [row])
            return

        tunnel = self._tunnels.establish(onion)
        if tunnel is None:
            with self._operation_lock:
                if self._is_pending(row):
                    self._log_tunnel_failure(onion)
            return
        conn, stream = tunnel
        db_id, _, content_type, payload, msg_id, timestamp = row

        try:
            conn.settimeout(self._config.get_float(SettingKey.STREAM_IDLE_TIMEOUT))
            early_ack = self._send_drop_row(
                conn, stream, row, partial(self._is_pending, row)
            )
            ack_line: Optional[str] = early_ack or stream.read_line()
            if self._handle_rejection(row, ack_line):
                return
            expected_ack = (
                is_expected_voice_commit_line(msg_id, ack_line)
                if content_type == ContentType.VOICE.value
                else is_expected_ack_line(msg_id, ack_line)
            )
            if not expected_ack:
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
        except DropDeliveryCancelled:
            pass
        except Exception:
            if self._is_pending(row):
                self._log_delivery_failure(onion, 'Drop delivery failed.', row=row)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def send_over_session(self, onion: str, messages: List[OutboxRow]) -> None:
        """Routes pending Drops over Live with sole receiver-owned socket reads.

        Voice uses a bounded transfer lease and waits for per-chunk and terminal
        responses. Text retains its asynchronous receiver-owned ACK handling.
        Failed attempts leave durable rows pending for the next worker pass.
        """
        conn: Optional[socket.socket] = self._state.get_connection(onion)
        if conn is None:
            return
        self._tunnels.close(onion)
        for row in messages:
            if (
                self._stop_flag.is_set()
                or self._state.get_connection(onion) is not conn
            ):
                return
            if not self._is_pending(row):
                continue
            db_id, _, content_type, payload, msg_id, timestamp = row
            if content_type == ContentType.TEXT.value:
                try:
                    self._state.send_frame(
                        conn,
                        build_drop_message(payload, msg_id, timestamp).encode('utf-8'),
                        self._row_claim(
                            row, lambda: self._state.get_connection(onion) is conn
                        ),
                    )
                except Exception:
                    return
                continue
            transfer = None
            try:
                transfer = self._state.begin_drop_transfer(
                    onion,
                    conn,
                    msg_id,
                    self._config.get_float(SettingKey.STREAM_IDLE_TIMEOUT),
                    self._stop_flag,
                    partial(self._is_pending, row),
                )
                early_ack = self._send_drop_row(
                    conn,
                    transfer,
                    row,
                    self._row_claim(
                        row,
                        partial(self._state.is_drop_transfer_current, conn, transfer),
                    ),
                )
                ack_line = early_ack or transfer.read_line()
                if self._handle_rejection(row, ack_line):
                    return
                if not is_expected_voice_commit_line(msg_id, ack_line):
                    raise ConnectionError(
                        'Live Drop completion acknowledgement missing.'
                    )
                self._finalize_delivery(
                    db_id,
                    onion,
                    content_type,
                    payload,
                    msg_id,
                    timestamp,
                    transport='session',
                )
            except DropDeliveryCancelled:
                return
            except Exception:
                if self._is_pending(row):
                    self._log_delivery_failure(onion, 'Drop delivery failed.', row=row)
                return
            finally:
                if transfer is not None:
                    self._state.finish_drop_transfer(conn, transfer)

    def _send_drop_row(
        self,
        conn: socket.socket,
        stream: DropResponseReader,
        row: OutboxRow,
        claim: Optional[Callable[[], bool]] = None,
    ) -> Optional[str]:
        """Sends one text or resumable Voice Drop through its response owner."""
        _, _, content_type, payload, msg_id, timestamp = row
        if content_type == ContentType.TEXT.value:
            if claim is not None and not claim():
                raise DropDeliveryCancelled('Text Drop delivery was cancelled.')
            self._state.send_frame(
                conn,
                build_drop_message(payload, msg_id, timestamp).encode('utf-8'),
                claim,
            )
            return None
        if content_type != ContentType.VOICE.value:
            raise ValueError('Unsupported DROP content type.')
        return self._voice_sender.send(conn, stream, payload, msg_id, timestamp, claim)

    def _is_pending(self, row: OutboxRow) -> bool:
        """Checks exact durable delivery ownership under the cancellation barrier."""
        db_id, onion, _, _, msg_id, _ = row
        with self._operation_lock:
            return not self._stop_flag.is_set() and self._mm.drop_delivery_pending(
                db_id, onion, msg_id
            )

    def _row_claim(
        self, row: OutboxRow, transport_claim: Callable[[], bool]
    ) -> Callable[[], bool]:
        """Binds immutable row identity and transport eligibility to queued frames."""
        return lambda: transport_claim() and self._is_pending(row)

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

    def _handle_rejection(self, row: OutboxRow, response_line: Optional[str]) -> bool:
        """Projects a peer rejection while leaving the durable row pending.

        Args:
            row: Exact durable delivery whose response was rejected.
            response_line (Optional[str]): The peer response frame.

        Returns:
            bool: True when the response was a rejection.
        """
        if response_line is None or not response_line.strip().startswith(
            TorCommand.REJECT.value
        ):
            return False
        with self._operation_lock:
            if not self._is_pending(row):
                return True
            _, onion, _, _, msg_id, _ = row
            reason: Optional[str] = parse_reject_reason(response_line)
            self._broadcast(DropFailedEvent(msg_id=msg_id, reason=reason))
            self._log_delivery_failure(
                onion,
                'Drop rejected by peer: ' + reason
                if reason
                else 'Drop rejected by peer.',
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
        if self._stop_flag.is_set():
            return
        with self._operation_lock:
            if self._stop_flag.is_set() or not self._mm.drop_delivery_pending(
                db_id, onion, msg_id
            ):
                return
            self._mm.update_message_status(db_id, MessageStatus.DELIVERED)
            if (
                content_type == ContentType.VOICE.value
                and self._blobs is not None
                and not self._mm.has_drop_payload(onion, msg_id)
            ):
                try:
                    metadata = json.loads(payload)
                    if isinstance(metadata, dict):
                        for blob_id in (
                            str(metadata['blob_id']),
                            *[str(item) for item in metadata.get('chunk_ids', [])],
                        ):
                            self._blobs.delete(blob_id, BlobLifecycle.PERSISTENT)
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

    def _log_delivery_failure(
        self, onion: str, detail: str, *, row: Optional[OutboxRow] = None
    ) -> None:
        """Records one failed drop delivery attempt.

        Args:
            onion (str): The target onion identity.
            detail (str): The failure detail.
            row: Optional exact delivery guard against cancelled attempt feedback.

        Returns:
            None
        """
        with self._operation_lock:
            if row is not None and not self._is_pending(row):
                return
            self._hm.log_event(
                HistoryEvent.FAILED,
                onion,
                actor=HistoryActor.SYSTEM,
                detail_text=detail,
            )
