"""Bounded wire pages from one coherent, runtime-owned metadata projection."""

from collections import OrderedDict
from dataclasses import replace
from secrets import token_hex
from threading import Lock
from typing import TypeVar

from metor.core.api import RuntimeSnapshotEvent, RuntimeSnapshotUnavailableEvent
from metor.shared.constants import Constants

Row = TypeVar('Row')


class SnapshotPages:
    """Retain a bounded number of immutable source inventories shared by readers."""

    def __init__(self) -> None:
        """Start with an empty inventory cache for this daemon runtime."""
        self._snapshots: OrderedDict[str, RuntimeSnapshotEvent] = OrderedDict()
        self._lock = Lock()

    def begin(self, snapshot: RuntimeSnapshotEvent) -> RuntimeSnapshotEvent:
        """Publish the first bounded page and retain only inventories needing another."""
        identity = token_hex(16)
        page = self._page(snapshot, identity, 0)
        if page.next_offset is not None:
            with self._lock:
                self._snapshots[identity] = snapshot
                if len(self._snapshots) > Constants.SNAPSHOT_PAGE_GENERATIONS:
                    self._snapshots.popitem(last=False)
        return page

    def read(
        self, identity: str, offset: int
    ) -> RuntimeSnapshotEvent | RuntimeSnapshotUnavailableEvent:
        """Return a page of that exact inventory, or require a fresh first page."""
        with self._lock:
            snapshot = self._snapshots.get(identity)
            if snapshot is None:
                return RuntimeSnapshotUnavailableEvent()
            self._snapshots.move_to_end(identity)
        if offset >= self._size(snapshot):
            return RuntimeSnapshotUnavailableEvent()
        return self._page(snapshot, identity, offset)

    @staticmethod
    def _size(snapshot: RuntimeSnapshotEvent) -> int:
        """Count every row in traversal order."""
        return (
            len(snapshot.pending)
            + len(snapshot.live_contexts)
            + len(snapshot.conversations)
            + len(snapshot.contacts)
        )

    @classmethod
    def _page(
        cls, snapshot: RuntimeSnapshotEvent, identity: str, offset: int
    ) -> RuntimeSnapshotEvent:
        """Select consecutive entries that fit both the item and wire budgets."""
        total = cls._size(snapshot)
        count = min(total - offset, Constants.SNAPSHOT_PAGE_ITEMS)
        while True:
            skip = offset
            remaining = count

            def take(section: list[Row]) -> list[Row]:
                """Consume the next slice without copying the entire source inventory."""
                nonlocal skip, remaining
                chunk = section[skip : skip + remaining]
                remaining -= len(chunk)
                skip = max(0, skip - len(section))
                return chunk

            end = offset + count
            page = replace(
                snapshot,
                pending=take(snapshot.pending),
                live_contexts=take(snapshot.live_contexts),
                conversations=take(snapshot.conversations),
                contacts=take(snapshot.contacts),
                snapshot_id=identity if total > count else None,
                page_offset=offset,
                next_offset=end if end < total else None,
            )
            # Reserve the IPC envelope and each recipient's projected invitation
            # handles, which are assigned after the common page is selected.
            projected_overhead = 1024 + 64 * (
                len(page.pending) + len(page.live_contexts)
            )
            if (
                len(page.to_json().encode('utf-8')) + projected_overhead
                <= Constants.SNAPSHOT_PAGE_BYTES
            ):
                return page
            if count <= 1:
                raise ValueError('Individual snapshot entry exceeds the page budget')
            count //= 2
