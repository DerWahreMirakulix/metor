"""Bounded, resumable Voice transfer over authenticated LIVE sessions."""

import base64
import binascii
import json
import threading
from typing import TYPE_CHECKING, Callable, Optional

from metor.core.api import (
    IpcEvent,
)
from metor.data import (
    ContactManager,
    MessageManager,
)
from metor.data.blob import BlobStore
from metor.utils import Constants

# Local Package Imports
from ..state import StateTracker
from ...notify import NotificationPayload
from .capture import VoiceCaptureMixin
from .inbound import VoiceInboundMixin
from .models import VoiceTurn
from .outbound import VoiceOutboundMixin
from .retained import VoiceRetainedMixin

if TYPE_CHECKING:
    from metor.data.profile import Config


class VoiceTransferManager(
    VoiceInboundMixin, VoiceRetainedMixin, VoiceCaptureMixin, VoiceOutboundMixin
):
    """Owns bounded Voice capture, receive, resume, and fallback state."""

    def __init__(
        self,
        *,
        contacts: ContactManager,
        messages: MessageManager,
        blobs: BlobStore,
        state: StateTracker,
        broadcast: Callable[[IpcEvent], None],
        config: 'Config',
        has_clients_callback: Optional[Callable[[], bool]] = None,
        has_live_consumers_callback: Optional[Callable[[], bool]] = None,
        notify_callback: Optional[Callable[[NotificationPayload], None]] = None,
        transition_lock: Optional[threading.RLock] = None,
        purge_fence: Optional[threading.Event] = None,
    ) -> None:
        """Initializes Voice transfer state with existing message primitives.

        Args:
            contacts (object): Contact manager implementing target resolution.
            messages (MessageManager): Canonical message receipt/spool service.
            blobs (BlobStore): Profile-mode external object store.
            state (StateTracker): Shared LIVE transport state.
            broadcast (Callable[[IpcEvent], None]): Typed IPC broadcaster.
            config (object): Profile config implementing typed getters.
            has_clients_callback (Optional[Callable[[], bool]]): IPC-client check.
            has_live_consumers_callback (Optional[Callable[[], bool]]): Active
                interactive LIVE-consumer check.
            notify_callback (Optional[Callable]): Detached notification sink.
            transition_lock (Optional[threading.RLock]): Shared identity transition lock.
            purge_fence (Optional[threading.Event]): Destructive lifecycle fence.

        Returns:
            None
        """
        self._contacts = contacts
        self._messages = messages
        self._blobs = blobs
        self._state = state
        self._broadcast = broadcast
        self._config = config
        self._has_clients = has_clients_callback or (lambda: True)
        self._has_live_consumers = has_live_consumers_callback or (lambda: True)
        self._notify = notify_callback or (lambda _payload: None)
        self._lock = transition_lock or threading.RLock()
        self._purge_fence = purge_fence or threading.Event()
        self._outbound: dict[str, VoiceTurn] = {}
        self._inbound: dict[tuple[str, str], VoiceTurn] = {}
        self._reconcile_drop_ownership()
        self._hydrate_retained_turns()

    @staticmethod
    def decode_wire_payload(encoded: str) -> Optional[dict[str, object]]:
        """Strictly decodes one small Voice wire envelope.

        Args:
            encoded (str): Base64 JSON envelope.

        Returns:
            Optional[dict[str, object]]: Decoded object or None.
        """
        try:
            raw = base64.b64decode(encoded, validate=True)
            if len(raw) > Constants.MAX_STREAM_BYTES:
                return None
            value = json.loads(raw.decode('utf-8'))
        except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None
