"""Bounded volatile union of successfully drained PCM ranges, independent of source eviction."""

from collections import OrderedDict
import threading

from metor.ui.gui.constants import GuiLimits
from metor.core.api import Delivery, MessageDirectionCode

# Local Package Imports
from .models import PlaybackTarget


class PlaybackCoverage:
    """Tracks application handoff facts without storing audio or persistent listening history."""

    def __init__(self) -> None:
        """Creates an empty, synchronized current-activation ledger.

        Args:
            None
        Returns:
            None
        """
        self._items: OrderedDict[PlaybackTarget, list[tuple[int, int]]] = OrderedDict()
        self._released: OrderedDict[PlaybackTarget, None] = OrderedDict()
        self._count = 0
        self._closed = False
        self._lock = threading.Lock()

    def add(self, target: PlaybackTarget, start: int, end: int) -> None:
        """Unions an actually drained range; exceeding bounds forgets coverage conservatively.

        Args:
            target: Exact activation and media identity.
            start: Inclusive sample-aligned byte offset actually played.
            end: Exclusive sample-aligned byte offset successfully drained.
        Returns:
            None
        """
        if start < 0 or end <= start:
            return
        with self._lock:
            if self._closed or target in self._released:
                return
            previous = self._items.pop(target, [])
            self._count -= len(previous)
            merged: list[tuple[int, int]] = []
            for left, right in sorted([*previous, (start, end)]):
                if merged and left <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], right))
                else:
                    merged.append((left, right))
            if len(merged) > GuiLimits.PLAYBACK_COVERAGE_PER_ITEM:
                merged = [(start, end)]
            while self._items and (
                len(self._items) >= GuiLimits.LIVE_ITEMS
                or self._count + len(merged) > GuiLimits.PLAYBACK_COVERAGE_INTERVALS
            ):
                _, removed = self._items.popitem(last=False)
                self._count -= len(removed)
            self._items[target] = merged
            self._count += len(merged)

    def complete(self, target: PlaybackTarget, size: int) -> bool:
        """Checks exact full coverage without counting fetched, skipped or failed output.

        Args:
            target: Original source identity.
            size: Core-confirmed finalized total byte count.
        Returns:
            bool: Whether the union covers every accepted byte of a nonempty source.
        """
        with self._lock:
            return size > 0 and self._items.get(target) == [(0, size)]

    def released(self, target: PlaybackTarget) -> bool:
        """Reports a bounded positive Core release fact even after ordinary source eviction.

        Args:
            target: Exact original source identity.
        Returns:
            bool: Whether release was positively acknowledged in this activation.
        """
        with self._lock:
            return target in self._released

    def mark_released(self, target: PlaybackTarget) -> None:
        """Retains metadata only after positive release; never infers success from timeout.

        Args:
            target: Exact source acknowledged by Core.
        Returns:
            None
        """
        with self._lock:
            if self._closed:
                return
            self._count -= len(self._items.pop(target, []))
            self._released[target] = None
            self._released.move_to_end(target)
            while len(self._released) > GuiLimits.LIVE_ITEMS:
                self._released.popitem(last=False)

    def clear(self) -> None:
        """Revokes old workers and removes all profile-linked local listening metadata.

        Args:
            None
        Returns:
            None
        """
        with self._lock:
            self._closed = True
            self._items.clear()
            self._released.clear()
            self._count = 0

    def discard_scope(
        self,
        peer: str | None,
        delivery: Delivery,
        msg_id: str | None,
        direction: MessageDirectionCode | None,
    ) -> None:
        """Forgets heard ranges for explicitly cleared non-review items, including evicted sources.

        Args:
            peer: Exact selected peer, or all peers in the projection.
            delivery: Exact acknowledged clear projection.
            msg_id: Optional exact message identity.
            direction: Optional exact local direction.
        Returns:
            None
        """
        with self._lock:
            for target in tuple(self._items):
                if (
                    target.owner_token is None
                    and target.delivery is delivery
                    and (peer is None or target.peer == peer)
                    and (msg_id is None or target.msg_id == msg_id)
                    and (direction is None or target.direction is direction)
                ):
                    self._count -= len(self._items.pop(target))
