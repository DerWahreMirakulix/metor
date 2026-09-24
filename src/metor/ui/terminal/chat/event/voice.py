"""Bounded, metadata-only Voice notices for the text-oriented chat frontend."""

from collections import OrderedDict
import threading
import time
from typing import TYPE_CHECKING

from metor.shared import clean_onion
from metor.core.api import (
    ContentType,
    Delivery,
    ensure_request_id,
    InvalidTargetEvent,
    IpcEvent,
    ListRetainedMessagesCommand,
    MessageDirectionCode,
    RetainedMessagesEvent,
    RetainedMessagesUnavailableEvent,
    UnreadMessagesEvent,
    VoiceChunkReceivedEvent,
    VoiceDataEvent,
    VoiceFinalizedEvent,
    VoiceIncomingStartedEvent,
)
from metor.ui.terminal.constants import Constants
from metor.ui.terminal.content import VOICE_HINT
from metor.ui.terminal.models import StatusTone

# Local Package Imports
from metor.ui.terminal.chat.models import ChatMessageType

if TYPE_CHECKING:
    from metor.ui.terminal.chat.event.handler import EventHandler


class VoiceNotices:
    """Deduplicates inbound Voice metadata and scans a finite public inventory."""

    def __init__(self, handler: 'EventHandler') -> None:
        """Keeps only bounded UI state, never media bytes.

        Args:
            handler: Owning terminal event handler.
        Returns:
            None
        """
        self._handler = handler
        self._seen: OrderedDict[tuple[str, str, str], None] = OrderedDict()
        self._epoch: str | None = None
        self._scan_lock = threading.RLock()
        self._pages_remaining = 0
        self._pending_request_id: str | None = None
        self._pending_since: float = 0.0
        self._target_onion: str | None = None
        self._delivery: Delivery | None = None
        self._next_peers: OrderedDict[tuple[str, Delivery | None], None] = OrderedDict()

    def _remember(
        self, epoch: str | None, onion: str | None, alias: str, msg_id: str
    ) -> bool:
        """Records a completed inbound identity once within the bounded window.

        Args:
            epoch: Daemon generation of the event.
            onion: Stable peer identity, when supplied.
            alias: Fallback label for old metadata without an onion.
            msg_id: Logical message identity.
        Returns:
            bool: True if this identity has not yet been shown.
        """
        if epoch != self._epoch:
            self._seen.clear()
            self._epoch = epoch
        identity = onion or self._handler._session.get_peer_onion(alias)
        key = (
            epoch or '',
            clean_onion(identity) if identity else f'alias:{alias}',
            msg_id,
        )
        if key in self._seen:
            return False
        self._seen[key] = None
        if len(self._seen) > Constants.VOICE_NOTICE_IDS:
            self._seen.popitem(last=False)
        return True

    def seen(
        self, epoch: str | None, onion: str | None, alias: str, msg_id: str
    ) -> bool:
        """Checks whether another event already presented this Voice identity.

        Args:
            epoch: Daemon generation of the event.
            onion: Peer identity when available.
            alias: Peer alias fallback.
            msg_id: Logical message identity.
        Returns:
            bool: Whether the hint was already printed.
        """
        identity = onion or self._handler._session.get_peer_onion(alias)
        return (
            epoch or '',
            clean_onion(identity) if identity else f'alias:{alias}',
            msg_id,
        ) in self._seen

    def announce(
        self, epoch: str | None, onion: str | None, alias: str, msg_id: str
    ) -> bool:
        """Displays one content-free notice with a non-consuming inbox follow-up.

        Args:
            epoch: Daemon generation of the event.
            onion: Peer identity when available.
            alias: Current peer alias.
            msg_id: Logical message identity.
        Returns:
            bool: Whether a new notice was printed.
        """
        if not self._remember(epoch, onion, alias, msg_id):
            return False
        handler = self._handler
        handler._remember_peer(alias, onion)
        if alias and alias != handler._session.focused_alias:
            handler._print_peer_status(
                '{alias}: ' + VOICE_HINT + ' Use /inbox to check unread messages.',
                StatusTone.INFO,
                alias,
                onion,
            )
        else:
            handler._renderer.print_message(
                VOICE_HINT + ' Use /inbox to check unread messages.',
                msg_type=ChatMessageType.STATUS,
                tone=StatusTone.INFO,
            )
        return True

    def request_inventory(
        self, target: str | None = None, delivery: Delivery | None = None
    ) -> None:
        """Starts a finite, non-consuming inbound metadata scan.

        Args:
            target: Stable peer onion, or None for the startup inventory.
            delivery: Optional delivery filter for the peer scan.
        Returns:
            None
        """
        with self._scan_lock:
            if (
                self._pending_request_id is not None
                and time.monotonic() - self._pending_since
                > Constants.DEFAULT_IPC_TIMEOUT
            ):
                self._pages_remaining = 0
                self._pending_request_id = None
                self._next_peers.clear()
            if self._pages_remaining:
                if target and (target, delivery) != (
                    self._target_onion,
                    self._delivery,
                ):
                    self._next_peers[(target, delivery)] = None
                    if len(self._next_peers) > Constants.VOICE_INVENTORY_PAGES:
                        self._next_peers.popitem(last=False)
                return
            self._start_scan(target, delivery)

    def _start_scan(self, target: str | None, delivery: Delivery | None) -> None:
        """Begins one scan while holding the inventory lock.

        Args:
            target: Stable peer onion or None.
            delivery: Optional delivery filter.
        Returns:
            None
        """
        self._target_onion = target
        self._delivery = delivery
        self._pages_remaining = Constants.VOICE_INVENTORY_PAGES
        self._request_page(None)

    def _finish_scan(self) -> None:
        """Releases the active scan and starts a queued peer scan if needed.

        Args:
            None
        Returns:
            None
        """
        self._pages_remaining = 0
        self._pending_request_id = None
        if self._next_peers:
            pending, _ = self._next_peers.popitem(last=False)
            self._start_scan(*pending)

    def _request_page(self, cursor: str | None) -> None:
        """Registers and sends one correlated metadata page without waiting.

        Args:
            cursor: Stable inventory cursor or None for the first page.
        Returns:
            None
        """
        command = ListRetainedMessagesCommand(
            target=self._target_onion,
            delivery=self._delivery,
            direction=MessageDirectionCode.IN,
            cursor=cursor,
            limit=Constants.DEFAULT_RETAINED_PAGE_SIZE,
        )
        self._pending_request_id = ensure_request_id(command)
        self._pending_since = time.monotonic()
        try:
            self._handler._ipc.send_command(command)
        except Exception:
            self._pages_remaining = 0
            self._pending_request_id = None
            raise

    def handle(self, event: IpcEvent) -> bool:
        """Consumes only Voice control/metadata events, never audio payloads.

        Args:
            event: Typed public SDK event.
        Returns:
            bool: Whether the event was handled.
        """
        if isinstance(event, VoiceIncomingStartedEvent):
            self._handler._remember_peer(event.alias, event.onion)
            return True
        if isinstance(event, (VoiceChunkReceivedEvent, VoiceDataEvent)):
            return True
        if isinstance(event, VoiceFinalizedEvent):
            if event.direction is MessageDirectionCode.IN and event.onion:
                alias = self._handler._session.get_peer_alias(event.onion, None)
                self.announce(event.epoch, event.onion, alias or '', event.msg_id)
            return True
        if isinstance(event, UnreadMessagesEvent):
            if event.onion:
                self.request_inventory(target=event.onion)
            return False
        if isinstance(event, InvalidTargetEvent):
            with self._scan_lock:
                if (
                    self._pages_remaining
                    and event.request_id == self._pending_request_id
                ):
                    self._finish_scan()
            return False
        if isinstance(event, (RetainedMessagesEvent, RetainedMessagesUnavailableEvent)):
            with self._scan_lock:
                if (
                    not self._pages_remaining
                    or not event.request_id
                    or event.request_id != self._pending_request_id
                ):
                    return True
                if isinstance(event, RetainedMessagesUnavailableEvent):
                    self._finish_scan()
                    return True
                self._pages_remaining -= 1
                self._pending_request_id = None
                for item in event.messages:
                    if (
                        item.direction is MessageDirectionCode.IN
                        and item.content_type is ContentType.VOICE
                        and item.finalized
                        and (self._delivery is None or item.delivery is self._delivery)
                        and (
                            self._target_onion is None
                            or clean_onion(item.onion)
                            == clean_onion(self._target_onion)
                        )
                    ):
                        self.announce(event.epoch, item.onion, item.alias, item.msg_id)
                if self._target_onion is None and self._next_peers:
                    self._finish_scan()
                elif event.next_cursor and self._pages_remaining:
                    self._request_page(event.next_cursor)
                else:
                    if event.next_cursor:
                        self._handler._renderer.print_message(
                            'Voice inventory is truncated; some older messages may not be shown.',
                            msg_type=ChatMessageType.STATUS,
                            tone=StatusTone.SYSTEM,
                        )
                    self._finish_scan()
            return True
        return False
