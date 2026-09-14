"""Bounded same-runtime message presentation reconciled by exact public identities."""

from collections import OrderedDict
from dataclasses import asdict, dataclass, replace
import json
from typing import TYPE_CHECKING

from metor.core.api import (
    AckEvent,
    ContentType,
    Delivery,
    IpcEvent,
    MessageDirectionCode,
    MessageReceivedEvent,
    MessageStatusCode,
    ReadReceiptEvent,
    RetainedMessagesEvent,
    TextContent,
    VoiceChunkReceivedEvent,
    VoiceFinalizedEvent,
    VoiceIncomingStartedEvent,
)
from metor.ui.gui.constants import GuiLimits

if TYPE_CHECKING:
    from .controller import GuiController


def advanced_status(
    current: MessageStatusCode, incoming: MessageStatusCode
) -> MessageStatusCode:
    """Keeps positive consumption and delivery evidence across out-of-order updates.

    Args:
        current: Existing exact-item evidence.
        incoming: New exact-item evidence from Core.
    Returns:
        MessageStatusCode: Status that cannot downgrade known Read or Delivered.
    """
    if current is MessageStatusCode.READ:
        return current
    if (
        current is MessageStatusCode.DELIVERED
        and incoming is not MessageStatusCode.READ
    ):
        return current
    return incoming


@dataclass
class TranscriptItem:
    """Nonpersistent text or Voice descriptor; encoded audio belongs in the media cache."""

    peer: str
    delivery: Delivery
    direction: MessageDirectionCode
    msg_id: str
    text: str | None = None
    timestamp: str = ''
    status: MessageStatusCode = MessageStatusCode.UNREAD
    codec: str | None = None
    size_bytes: int = 0
    finalized: bool = False
    duration_ms: int | None = None
    interrupted: bool = False
    order: int = 0


class Transcript:
    """Preserves ordered identities with explicit bounded admission and no disk mirror."""

    def __init__(self, controller: 'GuiController') -> None:
        """Creates an empty transcript tied to one GUI activation.

        Args:
            controller: Current public-service coordinator.
        Returns:
            None
        """
        self.controller = controller
        self.items: OrderedDict[
            tuple[str, Delivery, MessageDirectionCode, str], TranscriptItem
        ] = OrderedDict()
        self._sizes: dict[tuple[str, Delivery, MessageDirectionCode, str], int] = {}
        self.bytes = 0
        self.reserved_bytes = 0
        self.reserved_items = 0
        self._order = 0

    def next_order(self) -> int:
        """Allocates a same-runtime chronology slot shared by text and local capture.

        Args:
            None
        Returns:
            int: Monotonic local item order, independent of finalization time.
        """
        self._order += 1
        return self._order

    def capacity(self) -> tuple[int, int]:
        """Reports remaining capacity including capture metadata and in-flight reservations.

        Args:
            None
        Returns:
            tuple[int, int]: Available item count and serialized metadata bytes.
        """
        capture_count, capture_bytes = self.controller.voice.presentation_usage()
        return (
            GuiLimits.LIVE_ITEMS
            - capture_count
            - len(self.items)
            - self.reserved_items
            - len(self.controller.text.reservations),
            GuiLimits.LIVE_METADATA_BYTES
            - self.bytes
            - capture_bytes
            - self.reserved_bytes
            - sum(size for _item, size in self.controller.text.reservations.values()),
        )

    def admit(self, item: TranscriptItem) -> bool:
        """Updates one stable item, refusing excess metadata without consuming Core content.

        Args:
            item: Fully qualified plain presentation value.
        Returns:
            bool: Whether the item fits the current runtime's budget.
        """
        key = (item.peer, item.delivery, item.direction, item.msg_id)
        previous = self.items.get(key)
        if previous is not None:
            item = replace(item, status=advanced_status(previous.status, item.status))
        if not item.order:
            item = replace(
                item, order=previous.order if previous else self.next_order()
            )
        size = len(json.dumps(asdict(item)).encode('utf-8'))
        free_items, free_bytes = self.capacity()
        if (
            key not in self.items
            and free_items <= 0
            or size - self._sizes.get(key, 0) > free_bytes
        ):
            self.controller.state.status = 'Conversation view is full. New content remains available in the service.'
            return False
        self.bytes += size - self._sizes.get(key, 0)
        self._sizes[key] = size
        self.items[key] = item
        return True

    def install(self, event: IpcEvent) -> bool:
        """Reconciles metadata without consuming voice or inventing remote read status.

        Args:
            event: Current activation's public event or inventory response.
        Returns:
            bool: Whether the event affects message presentation.
        """
        item: TranscriptItem | None
        if isinstance(event, RetainedMessagesEvent):
            for entry in event.messages:
                if (
                    entry.direction is MessageDirectionCode.OUT
                    and entry.status is MessageStatusCode.DRAFT
                ):
                    continue
                if entry.content_type is ContentType.VOICE:
                    key = (entry.onion, entry.delivery, entry.direction, entry.msg_id)
                    item = self.items.get(key) or TranscriptItem(*key)
                    self.admit(
                        replace(
                            item,
                            status=entry.status,
                            codec=entry.codec,
                            size_bytes=entry.size_bytes,
                            finalized=entry.finalized,
                            duration_ms=entry.duration_ms,
                            interrupted=entry.producer_interrupted,
                        )
                    )
            return True
        if isinstance(event, MessageReceivedEvent) and event.onion and event.msg_id:
            self.controller.handoff.needed = True
            if isinstance(event.content, TextContent):
                self.admit(
                    TranscriptItem(
                        event.onion,
                        event.delivery,
                        MessageDirectionCode.IN,
                        event.msg_id,
                        event.content.text,
                        event.timestamp or '',
                    )
                )
            return True
        if isinstance(event, VoiceIncomingStartedEvent) and event.onion:
            key = (event.onion, event.delivery, MessageDirectionCode.IN, event.msg_id)
            fresh = key not in self.items
            admitted = self.admit(
                self.items.get(key)
                or TranscriptItem(*key, codec=event.codec, size_bytes=event.next_offset)
            )
            if fresh and admitted:
                self.controller.playback.incoming(event)
            return True
        if isinstance(event, VoiceChunkReceivedEvent) and event.onion:
            key = (event.onion, event.delivery, MessageDirectionCode.IN, event.msg_id)
            item = self.items.get(key)
            if item is not None:
                # Encoded bytes remain in Core; playback uses its bounded range API.
                padding = len(event.data) - len(event.data.rstrip('='))
                size = event.offset + len(event.data) // 4 * 3 - padding
                self.admit(replace(item, size_bytes=max(item.size_bytes, size)))
            return True
        if (
            isinstance(event, VoiceFinalizedEvent)
            and event.onion
            and event.direction
            and event.delivery
        ):
            key = (event.onion, event.delivery, event.direction, event.msg_id)
            item = self.items.get(key)
            if item is not None:
                self.admit(
                    replace(
                        item,
                        size_bytes=event.size_bytes,
                        finalized=True,
                        duration_ms=event.duration_ms,
                    )
                )
            return True
        if isinstance(event, (AckEvent, ReadReceiptEvent)):
            turn = self.controller.voice.live_turns.get(event.msg_id)
            if turn is not None and (
                not isinstance(event, ReadReceiptEvent)
                or turn.binding.peer == event.onion
            ):
                turn.status = advanced_status(
                    turn.status,
                    MessageStatusCode.READ
                    if isinstance(event, ReadReceiptEvent)
                    else MessageStatusCode.DELIVERED,
                )
            for item in list(self.items.values()):
                if (
                    item.msg_id == event.msg_id
                    and item.direction is MessageDirectionCode.OUT
                    and (
                        not isinstance(event, ReadReceiptEvent)
                        or item.peer == event.onion
                    )
                ):
                    self.admit(
                        replace(
                            item,
                            status=MessageStatusCode.READ
                            if isinstance(event, ReadReceiptEvent)
                            else MessageStatusCode.DELIVERED,
                        )
                    )
            return True
        return False

    def discard(
        self,
        peer: str | None,
        delivery: Delivery,
        msg_id: str | None = None,
        direction: MessageDirectionCode | None = None,
    ) -> None:
        """Removes only positively cleared local presentation identities.

        Args:
            peer: Exact peer, or None for an acknowledged all-DROP clear.
            delivery: Explicit projection whose copies are being removed.
            msg_id: Exact message, or None for the selected conversation.
            direction: Exact direction for a single-message action.
        Returns:
            None
        """
        for key in tuple(self.items):
            if (
                key[1] is delivery
                and (peer is None or key[0] == peer)
                and (msg_id is None or key[3] == msg_id)
                and (direction is None or key[2] is direction)
            ):
                self.items.pop(key)
                self.bytes -= self._sizes.pop(key, 0)

    def clear(self) -> None:
        """Releases all owner-specific plain content on profile or runtime loss.

        Args:
            None
        Returns:
            None
        """
        self.items.clear()
        self._sizes.clear()
        self.bytes = 0
        self.reserved_items = self.reserved_bytes = 0
