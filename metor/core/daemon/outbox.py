"""
Module defining the background worker for sending asynchronous offline messages.
Routinely checks the database outbox and dispatches ASYNC Tor connections.
"""

import socket
import threading
import time
import base64
from typing import List, Optional

from metor.core.tor import TorManager
from metor.data.messages import MessageManager, MessageStatus
from metor.data.history import HistoryManager, HistoryEvent
from metor.core.daemon.crypto import Crypto
from metor.core.daemon.models import TorCommand


class OutboxWorker:
    """Background service for processing the Drop & Go offline message queue."""

    def __init__(
        self,
        tm: TorManager,
        mm: MessageManager,
        hm: HistoryManager,
        crypto: Crypto,
        stop_flag: threading.Event,
    ) -> None:
        """
        Initializes the OutboxWorker.

        Args:
            tm (TorManager): The Tor network manager for outbound connections.
            mm (MessageManager): The database manager for accessing pending messages.
            hm (HistoryManager): The history logger.
            crypto (Crypto): The cryptographic service for handshakes.
            stop_flag (threading.Event): Event to gracefully shutdown the worker loop.
        """
        self._tm: TorManager = tm
        self._mm: MessageManager = mm
        self._hm: HistoryManager = hm
        self._crypto: Crypto = crypto
        self._stop_flag: threading.Event = stop_flag

    def start(self) -> None:
        """Starts the worker loop in a background thread."""
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self) -> None:
        """Target execution loop checking the database for pending drops."""
        while not self._stop_flag.is_set():
            time.sleep(10)  # Check interval
            pending_rows: List[tuple] = self._mm.get_pending_outbox()

            for row in pending_rows:
                db_id, target_onion, msg_type, payload = row

                try:
                    conn: socket.socket = self._tm.connect(target_onion)
                    conn.settimeout(10)

                    challenge_data: bytes = conn.recv(1024)
                    challenge: str = challenge_data.decode().strip().split(' ')[1]
                    signature: Optional[str] = self._crypto.sign_challenge(challenge)

                    if not signature:
                        continue

                    # Send the ASYNC flag during the handshake
                    auth_msg: str = (
                        f'{TorCommand.AUTH.value} {self._tm.onion} {signature} ASYNC\n'
                    )
                    conn.sendall(auth_msg.encode('utf-8'))

                    b64_payload: str = base64.b64encode(payload.encode('utf-8')).decode(
                        'utf-8'
                    )
                    drop_msg: str = f'{TorCommand.DROP.value} {db_id} {b64_payload}\n'
                    conn.sendall(drop_msg.encode('utf-8'))

                    ack_data: bytes = conn.recv(1024)
                    if (
                        ack_data
                        and f'{TorCommand.ACK.value} {db_id}'
                        in ack_data.decode('utf-8')
                    ):
                        self._mm.update_message_status(db_id, MessageStatus.DELIVERED)
                        self._hm.log_event(
                            HistoryEvent.ASYNC_SENT,
                            target_onion,
                            'Offline message delivered',
                        )

                except Exception:
                    # Connection failed or timeout. Remains PENDING for next iteration.
                    pass
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
