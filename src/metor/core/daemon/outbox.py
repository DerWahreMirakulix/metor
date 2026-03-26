"""
Module defining the background worker for sending asynchronous offline messages.
Routinely checks the database outbox and dispatches ASYNC Tor connections.
"""

import socket
import threading
import time
import base64
from typing import List, Optional, Tuple

from metor.core.tor import TorManager
from metor.data.message import MessageManager, MessageStatus
from metor.data.history import HistoryManager, HistoryEvent

# Local Package Imports
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

        Returns:
            None
        """
        self._tm: TorManager = tm
        self._mm: MessageManager = mm
        self._hm: HistoryManager = hm
        self._crypto: Crypto = crypto
        self._stop_flag: threading.Event = stop_flag

    def start(self) -> None:
        """
        Starts the worker loop in a background thread.

        Args:
            None

        Returns:
            None
        """
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self) -> None:
        """
        Target execution loop checking the database for pending drops.

        Args:
            None

        Returns:
            None
        """
        while not self._stop_flag.is_set():
            time.sleep(10)
            pending_rows: List[Tuple[int, str, str, str]] = (
                self._mm.get_pending_outbox()
            )

            for row in pending_rows:
                db_id, target_onion, _, payload = row

                try:
                    conn: socket.socket = self._tm.connect(target_onion)
                    conn.settimeout(10)

                    buffer: str = ''
                    while '\n' not in buffer:
                        chunk: bytes = conn.recv(4096)
                        if not chunk:
                            raise ConnectionError(
                                'Connection dropped during challenge.'
                            )
                        buffer += chunk.decode('utf-8')

                    challenge_line, buffer = buffer.split('\n', 1)
                    challenge: str = challenge_line.strip().split(' ')[1]
                    signature: Optional[str] = self._crypto.sign_challenge(challenge)

                    if not signature:
                        continue

                    auth_msg: str = (
                        f'{TorCommand.AUTH.value} {self._tm.onion} {signature} ASYNC\n'
                    )
                    conn.sendall(auth_msg.encode('utf-8'))

                    b64_payload: str = base64.b64encode(payload.encode('utf-8')).decode(
                        'utf-8'
                    )
                    drop_msg: str = f'{TorCommand.DROP.value} {db_id} {b64_payload}\n'
                    conn.sendall(drop_msg.encode('utf-8'))

                    while '\n' not in buffer:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        buffer += chunk.decode('utf-8')

                    if '\n' in buffer:
                        ack_line, buffer = buffer.split('\n', 1)
                        if f'{TorCommand.ACK.value} {db_id}' in ack_line:
                            self._mm.update_message_status(
                                db_id, MessageStatus.DELIVERED
                            )
                            self._hm.log_event(
                                HistoryEvent.ASYNC_SENT,
                                target_onion,
                                'Offline message delivered',
                            )

                except Exception:
                    pass
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
