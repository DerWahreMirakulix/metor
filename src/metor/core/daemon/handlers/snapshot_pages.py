"""Bounded wire pages from one coherent, runtime-owned metadata projection."""

from collections import OrderedDict
from dataclasses import replace
from secrets import token_hex
from threading import Lock
from typing import TypeVar

from metor.core.api import (
    ContactsDataEvent,
    RuntimeSnapshotEvent,
    RuntimeSnapshotUnavailableEvent,
)
from metor.shared.constants import Constants

Row = TypeVar('Row')
Snapshot = RuntimeSnapshotEvent | ContactsDataEvent


class SnapshotPages:
    """Retain a bounded number of immutable source inventories shared by readers."""

    def __init__(self) -> None:
        """Start with an empty inventory cache for this daemon runtime."""
        self._snapshots: OrderedDict[str, Snapshot] = OrderedDict()
        self._lock = Lock()

    def begin(self, snapshot: Snapshot) -> Snapshot:
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
    ) -> Snapshot | RuntimeSnapshotUnavailableEvent:
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
    def _size(snapshot: Snapshot) -> int:
        """Count every row in traversal order."""
        if isinstance(snapshot, ContactsDataEvent):
            return len(snapshot.saved) + len(snapshot.discovered)
        return (
            len(snapshot.pending)
            + len(snapshot.live_contexts)
            + len(snapshot.conversations)
            + len(snapshot.contacts)
        )

    @classmethod
    def _page(cls, snapshot: Snapshot, identity: str, offset: int) -> Snapshot:
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
            page: Snapshot
            if isinstance(snapshot, ContactsDataEvent):
                page = replace(
                    snapshot,
                    saved=take(snapshot.saved),
                    discovered=take(snapshot.discovered),
                )
                projected_overhead = 1024
            else:
                page = replace(
                    snapshot,
                    pending=take(snapshot.pending),
                    live_contexts=take(snapshot.live_contexts),
                    conversations=take(snapshot.conversations),
                    contacts=take(snapshot.contacts),
                )
                # Recipient-specific invitation handles are assigned after paging.
                projected_overhead = 1024 + 64 * (
                    len(page.pending) + len(page.live_contexts)
                )
            page.snapshot_id = identity if total > count else None
            page.page_offset = offset
            page.next_offset = end if end < total else None
            if (
                len(page.to_json().encode('utf-8')) + projected_overhead
                <= Constants.SNAPSHOT_PAGE_BYTES
            ):
                return page
            if count <= 1:
                raise ValueError('Individual snapshot entry exceeds the page budget')
            count //= 2
