"""Bounded volatile source retention with explicit privacy revocation."""

from collections import OrderedDict
from bisect import bisect_right
from contextlib import contextmanager
import threading
from typing import Iterator

from metor.core.api import Delivery, MessageDirectionCode
from metor.ui.gui.constants import GuiLimits

# Local Package Imports
from .models import PlaybackTarget
from .coverage import PlaybackCoverage
from .envelope import PcmEnvelope


class MediaCache:
    """Retains only complete sequential source prefixes within one shared byte budget."""

    def __init__(self) -> None:
        """Creates an empty synchronized memory-only source cache.

        Args:
            None
        Returns:
            None
        """
        self._items: OrderedDict[PlaybackTarget, list[bytearray]] = OrderedDict()
        self._offsets: dict[PlaybackTarget, list[int]] = {}
        self._envelopes: dict[PlaybackTarget, PcmEnvelope] = {}
        self._sizes: dict[PlaybackTarget, int] = {}
        self._complete: set[PlaybackTarget] = set()
        self._discarded: OrderedDict[PlaybackTarget, None] = OrderedDict()
        self._closed = False
        self._leases: dict[PlaybackTarget, int] = {}
        self._bytes = 0
        self._lock = threading.Lock()
        self.coverage = PlaybackCoverage()

    def append(
        self, target: PlaybackTarget, offset: int, payload: bytes, *, complete: bool
    ) -> bool:
        """Caches one contiguous range, refusing gaps and evicting old inactive sources.

        Args:
            target: Exact current-activation source.
            offset: Source range start.
            payload: Immutable encoded range owned by the cache after admission.
            complete: Whether Core confirmed this is the finalized end.
        Returns:
            bool: Whether a complete prefix remains cached.
        """
        with self._lock:
            if self._closed or target in self._discarded:
                return False
            current = self._sizes.get(target, 0)
            if offset < current:
                return target in self._items
            if target in self._complete:
                return not payload and complete
            if (
                offset != current
                or current + len(payload) > GuiLimits.MEDIA_CACHE_BYTES
            ):
                self._remove(target)
                return False
            while self._items and (
                self._bytes + len(payload) > GuiLimits.MEDIA_CACHE_BYTES
                or target not in self._items
                and len(self._items) >= GuiLimits.LIVE_ITEMS
            ):
                other = next(
                    (
                        key
                        for key in self._items
                        if key != target and not self._leases.get(key)
                    ),
                    None,
                )
                if other is None:
                    return False
                self._remove(other)
            chunks = self._items.setdefault(target, [])
            if payload:
                view = memoryview(payload)
                consumed = 0
                while consumed < len(view):
                    if (
                        not chunks
                        or len(chunks[-1]) == GuiLimits.MEDIA_CACHE_BLOCK_BYTES
                    ):
                        chunks.append(bytearray())
                        self._offsets.setdefault(target, []).append(offset + consumed)
                    end = min(
                        len(view),
                        consumed + GuiLimits.MEDIA_CACHE_BLOCK_BYTES - len(chunks[-1]),
                    )
                    chunks[-1].extend(view[consumed:end])
                    consumed = end
                envelope = self._envelopes.get(target)
                if envelope is None:
                    envelope = self._envelopes[target] = PcmEnvelope()
                envelope.append(offset, payload)
            self._sizes[target] = current + len(payload)
            self._bytes += len(payload)
            self._items.move_to_end(target)
            if complete:
                self._complete.add(target)
            return True

    def read(
        self, target: PlaybackTarget, offset: int, maximum: int
    ) -> tuple[bytes, int] | None:
        """Copies at most one bounded range of a confirmed complete retained source.

        Args:
            target: Exact original source identity.
            offset: Requested complete-sample offset.
            maximum: Decoder range ceiling.
        Returns:
            tuple[bytes, int] | None: Range and total length, or unavailable cache.
        """
        with self._lock:
            if (
                target not in self._complete
                or not 0 < maximum <= GuiLimits.DECODE_BYTES
            ):
                return None
            size = self._sizes[target]
            if not 0 <= offset <= size:
                return None
            if offset < size:
                offsets = self._offsets[target]
                index = bisect_right(offsets, offset) - 1
                local = offset - offsets[index]
                chunk = self._items[target][index]
                return bytes(chunk[local : local + maximum]), size
            return b'', size

    def targets(self) -> tuple[PlaybackTarget, ...]:
        """Snapshots bounded source identities without copying encoded bytes.

        Args:
            None
        Returns:
            tuple[PlaybackTarget, ...]: Current exact retained source metadata.
        """
        with self._lock:
            return tuple(self._items)

    def envelope(self, target: PlaybackTarget) -> tuple[int, tuple[int | None, ...]]:
        """Returns bounded real PCM amplitude metadata without reading Core or consuming Voice.

        Args:
            target: Exact retained source identity.
        Returns:
            tuple: Bytes per amplitude bin and known peaks, or an empty unavailable summary.
        """
        with self._lock:
            envelope = self._envelopes.get(target)
            return envelope.snapshot() if envelope else (0, ())

    def complete_size(self, target: PlaybackTarget) -> int | None:
        """Reports complete retained source availability without copying encoded bytes.

        Args:
            target: Exact activation-qualified source identity.
        Returns:
            int | None: Confirmed complete size, or unavailable source.
        """
        with self._lock:
            return self._sizes.get(target) if target in self._complete else None

    def mark_complete(self, target: PlaybackTarget, size: int) -> bool:
        """Marks only an already cached full prefix after exact Core finalization.

        Args:
            target: Original capture source; no bytes are refetched.
            size: Core-confirmed finalized encoded size.
        Returns:
            bool: Whether all finalized bytes remain retained.
        """
        with self._lock:
            if (
                self._closed
                or target not in self._items
                or self._sizes.get(target) != size
            ):
                return False
            self._complete.add(target)
            return True

    @contextmanager
    def retain(self, target: PlaybackTarget) -> Iterator[bool]:
        """Pins a complete source against ordinary cache eviction during bounded replay/resend.

        Explicit deletion, profile abandonment and purge still revoke the source.

        Args:
            target: Exact complete source to lease.
        Returns:
            Iterator[bool]: Whether the complete source was retained for this operation.
        """
        with self._lock:
            available = target in self._complete and not self._closed
            if available:
                self._leases[target] = self._leases.get(target, 0) + 1
        try:
            yield available
        finally:
            if available:
                with self._lock:
                    remaining = self._leases.get(target, 0) - 1
                    if remaining > 0:
                        self._leases[target] = remaining
                    else:
                        self._leases.pop(target, None)

    def _remove(self, target: PlaybackTarget) -> None:
        """Drops a source while the cache lock is held.

        Args:
            target: Exact source to evict.
        Returns:
            None
        """
        self._bytes -= self._sizes.pop(target, 0)
        self._items.pop(target, None)
        self._offsets.pop(target, None)
        self._envelopes.pop(target, None)
        self._complete.discard(target)
        self._leases.pop(target, None)

    def released(self, target: PlaybackTarget) -> bool:
        """Reports bounded confirmed release independently of source eviction.

        Args:
            target: Exact inbound identity.
        Returns:
            bool: Whether Core has positively confirmed release.
        """
        return self.coverage.released(target)

    def mark_released(self, target: PlaybackTarget) -> None:
        """Remembers positive release without retaining an additional encoded source.

        Args:
            target: Exact inbound identity confirmed by Core.
        Returns:
            None
        """
        self.coverage.mark_released(target)

    def discard(self, target: PlaybackTarget) -> None:
        """Drops an explicitly deleted or departed review source.

        Args:
            target: Exact source to release.
        Returns:
            None
        """
        self.coverage.discard_scope(
            target.peer, target.delivery, target.msg_id, target.direction
        )
        with self._lock:
            self._remove(target)
            self._discarded[target] = None
            while len(self._discarded) > GuiLimits.LIVE_ITEMS:
                self._discarded.popitem(last=False)

    def discard_scope(
        self,
        peer: str | None,
        delivery: Delivery,
        msg_id: str | None = None,
        direction: MessageDirectionCode | None = None,
    ) -> None:
        """Drops cleared conversation copies while preserving uncommitted owner-qualified reviews.

        Args:
            peer: Exact peer, or None for all peers in the selected projection.
            delivery: Explicit projection affected by acknowledged local cleanup.
            msg_id: Optional exact message identity.
            direction: Optional exact direction, never inferred from the message ID.
        Returns:
            None
        """
        self.coverage.discard_scope(peer, delivery, msg_id, direction)
        with self._lock:
            for target in tuple(self._items):
                if (
                    target.owner_token is None
                    and target.delivery is delivery
                    and (peer is None or target.peer == peer)
                    and (msg_id is None or target.msg_id == msg_id)
                    and (direction is None or target.direction is direction)
                ):
                    self._remove(target)
                    self._discarded[target] = None
            while len(self._discarded) > GuiLimits.LIVE_ITEMS:
                self._discarded.popitem(last=False)

    def clear(self) -> None:
        """Releases all profile-owned encoded references on owner loss.

        Args:
            None
        Returns:
            None
        """
        self.coverage.clear()
        with self._lock:
            self._items.clear()
            self._offsets.clear()
            self._envelopes.clear()
            self._sizes.clear()
            self._complete.clear()
            self._discarded.clear()
            self._bytes = 0
            self._closed = True
            self._leases.clear()
