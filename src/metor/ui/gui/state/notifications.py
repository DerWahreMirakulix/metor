"""Bounded volatile content-free notification entries and dismissal watermarks."""

from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from enum import Enum
import json
import time

from metor.core.api import Delivery
from metor.shared import Constants
from metor.ui.gui.constants import GuiLimits


class NoticeKind(str, Enum):
    """Permitted local notification vocabulary without remote body/detail fields."""

    DROP = 'new_drop'
    LIVE = 'new_live'
    CALL = 'incoming_live'
    PENDING = 'pending_live'
    UNSTABLE = 'connection_unstable'
    FALLBACK = 'queued_as_drop'


@dataclass(frozen=True)
class Notice:
    """One exact current fact or bounded transient observation, with no message payload."""

    kind: NoticeKind
    peer: str
    source: str
    count: int = 1
    actionable: bool = True
    seen: bool = False
    created_at: float = 0.0

    @property
    def key(self) -> tuple[NoticeKind, str]:
        """Returns a stable kind/peer coalescing identity.

        Args:
            None
        Returns:
            tuple[NoticeKind, str]: Local entry key, independent of alias.
        """
        return self.kind, self.peer

    @property
    def priority(self) -> int:
        """Keeps current calls and unresolved outbound actions ahead of informational churn.

        Args:
            None
        Returns:
            int: Lower values have stronger retention priority.
        """
        return (
            0
            if self.kind is NoticeKind.CALL
            else 1
            if self.kind is NoticeKind.PENDING
            else 2
            if self.actionable
            else 3
        )

    @property
    def delivery(self) -> Delivery:
        """Maps current notification meaning to a navigation-only projection.

        Args:
            None
        Returns:
            Delivery: Intended DROP or LIVE view.
        """
        return (
            Delivery.DROP
            if self.kind in {NoticeKind.DROP, NoticeKind.FALLBACK}
            else Delivery.LIVE
        )


class NotificationStore:
    """Keeps bounded entries, selection and source watermarks in memory only."""

    def __init__(self) -> None:
        """Creates an empty store with explicit count/byte accounting.

        Args:
            None
        Returns:
            None
        """
        self.items: OrderedDict[tuple[NoticeKind, str], Notice] = OrderedDict()
        self.watermarks: OrderedDict[tuple[NoticeKind, str], str] = OrderedDict()
        self.source_hints: OrderedDict[tuple[NoticeKind, str], str] = OrderedDict()
        self.selected: set[tuple[NoticeKind, str]] = set()
        self.selecting = False
        self.revision = 0

    @property
    def bytes(self) -> int:
        """Accounts entries and watermark metadata under the shared notification ceiling.

        Args:
            None
        Returns:
            int: Conservative serialized UTF-8 metadata size.
        """
        return len(
            json.dumps(
                {
                    'items': [asdict(item) for item in self.items.values()],
                    'watermarks': [
                        (kind.value, peer, source)
                        for (kind, peer), source in self.watermarks.items()
                    ],
                    'selected': [(kind.value, peer) for kind, peer in self.selected],
                    'source_hints': [
                        (kind.value, peer, source)
                        for (kind, peer), source in self.source_hints.items()
                    ],
                }
            ).encode('utf-8')
        )

    def hint(self, key: tuple[NoticeKind, str], source: str) -> None:
        """Remembers a bounded content-free arrival identity for equal-count replacement.

        Args:
            key: Permitted kind and canonical peer.
            source: Fixed-size hash of an exact current arrival identity.
        Returns:
            None
        """
        if len(key[1]) > Constants.TOR_V3_ONION_ADDRESS_LENGTH or len(source) != 64:
            return
        self.source_hints[key] = source
        self.source_hints.move_to_end(key)
        while (
            len(self.source_hints) > GuiLimits.NOTIFICATIONS
            or self.bytes > GuiLimits.NOTIFICATION_BYTES
        ):
            self.source_hints.popitem(last=False)

    def put(self, notice: Notice) -> bool:
        """Admits exact facts without recreating dismissed unchanged source state.

        Args:
            notice: Strict content-free current fact.
        Returns:
            bool: Whether the fact is retained within the finite budgets.
        """
        if (
            len(notice.peer.encode('utf-8')) > Constants.TOR_V3_ONION_ADDRESS_LENGTH
            or len(notice.source) > GuiLimits.DEVICE_STRING
            or notice.count < 1
        ):
            return False
        if self.watermarks.get(notice.key) == notice.source:
            return False
        old = self.items.get(notice.key)
        if (
            old is not None
            and old.source == notice.source
            and old.count == notice.count
        ):
            return True
        if old is None and len(self.items) >= GuiLimits.NOTIFICATIONS:
            victim = next(
                (
                    key
                    for key, item in self.items.items()
                    if item.priority > notice.priority
                ),
                None,
            )
            if victim is None:
                return False
            self.items.pop(victim)
            self.selected.discard(victim)
        self.items[notice.key] = replace(
            notice, created_at=notice.created_at or time.time()
        )
        if self.bytes > GuiLimits.NOTIFICATION_BYTES:
            self.items.pop(notice.key)
            if old is not None:
                self.items[old.key] = old
            return False
        self.items.move_to_end(notice.key)
        self.revision += 1
        return True

    def reconcile(self, current: Iterable[Notice]) -> None:
        """Resolves stale facts while retaining only bounded source identities.

        Args:
            current: Lazy current candidates derived from existing Core projections.
        Returns:
            None
        """
        tracked = set(self.items) | set(self.watermarks)
        sources: dict[tuple[NoticeKind, str], str] = {}
        candidates: dict[tuple[NoticeKind, str], Notice] = {}
        for item in current:
            if item.key in tracked:
                sources[item.key] = item.source
            if len(candidates) < GuiLimits.NOTIFICATIONS:
                candidates[item.key] = item
            elif item.key not in candidates:
                victim = max(candidates, key=lambda key: candidates[key].priority)
                if candidates[victim].priority > item.priority:
                    candidates.pop(victim)
                    candidates[item.key] = item
        for key in tracked:
            old = self.items.get(key)
            if old is not None and old.actionable and key not in sources:
                self.items.pop(key)
                self.selected.discard(key)
                self.revision += 1
        for key in tuple(self.watermarks):
            if key not in sources or self.watermarks[key] != sources[key]:
                self.watermarks.pop(key)
        for item in candidates.values():
            self.put(item)

    def mark_seen(self) -> None:
        """Marks only presented center entries seen; never consumes any Core message.

        Args:
            None
        Returns:
            None
        """
        for key, item in tuple(self.items.items()):
            if not item.seen:
                self.items[key] = replace(item, seen=True)
                self.revision += 1

    def dismiss(self, keys: set[tuple[NoticeKind, str]]) -> None:
        """Drops presentation entries and remembers exact current source state.

        Args:
            keys: Explicit selected/dismissed current entry identities.
        Returns:
            None
        """
        for key in keys:
            item = self.items.pop(key, None)
            if item is not None and item.actionable:
                self.watermarks[key] = item.source
                self.watermarks.move_to_end(key)
            self.selected.discard(key)
        while (
            len(self.watermarks) > GuiLimits.NOTIFICATIONS
            or self.bytes > GuiLimits.NOTIFICATION_BYTES
        ):
            self.watermarks.popitem(last=False)
        self.revision += 1

    def clear_center(self) -> None:
        """Clears only the volatile center, preserving Core messages and current root facts.

        Args:
            None
        Returns:
            None
        """
        self.dismiss(set(self.items))
        self.selecting = False

    def abandon(self) -> None:
        """Releases all profile-linked notification state on activation loss.

        Args:
            None
        Returns:
            None
        """
        self.items.clear()
        self.watermarks.clear()
        self.source_hints.clear()
        self.selected.clear()
        self.selecting = False
        self.revision += 1
