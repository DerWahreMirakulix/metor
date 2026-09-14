"""Presentation routes and volatile drafts; authoritative facts remain SDK DTOs."""

from dataclasses import dataclass, field

from metor.core.api import Delivery, RuntimeSnapshotEvent, GuiPreferencesEvent
from metor.ui.gui.constants import GuiLimits


@dataclass(frozen=True)
class Route:
    """One foreground projection, independently of root selection."""

    view: str = 'V01'
    peer: str | None = None
    delivery: Delivery = Delivery.DROP
    history_raw: bool = False


@dataclass
class GuiState:
    """Owns bounded volatile presentation and never creates Core authorization."""

    generation: int = 0
    root_delivery: Delivery = Delivery.DROP
    root_pages: dict[Delivery, int] = field(default_factory=dict)
    secondary_scroll: dict[Route, float] = field(default_factory=dict)
    route: Route = field(default_factory=Route)
    back_stack: list[Route] = field(default_factory=list)
    snapshot: RuntimeSnapshotEvent | None = None
    preferences: GuiPreferencesEvent | None = None
    capabilities: frozenset[str] = frozenset()
    covered: bool = True
    busy: bool = False
    status: str = ''
    drafts: dict[tuple[str, Delivery], str] = field(default_factory=dict)

    def navigate(self, route: Route) -> None:
        """Changes only presentation; callers perform input finalization first.

        Args:
            route: Destination with exact peer and projection.
        Returns:
            None
        """
        if route != self.route:
            if len(self.back_stack) >= GuiLimits.TEXT_CONTEXTS:
                self.back_stack.pop(0)
            self.back_stack.append(self.route)
            self.route = route

    def back(self) -> None:
        """Returns to the caller or the originating root without a command.

        Args:
            None
        Returns:
            None
        """
        self.route = (
            self.back_stack.pop()
            if self.back_stack
            else Route(
                'V06' if self.root_delivery == Delivery.DROP else 'V07',
                delivery=self.root_delivery,
            )
        )

    def set_draft(self, peer: str, delivery: Delivery, value: str) -> bool:
        """Refuses excess text growth without evicting another context's draft.

        Args:
            peer: Canonical peer identity.
            delivery: Explicit composer projection.
            value: Proposed canonical text.
        Returns:
            bool: Whether the bounded draft was accepted.
        """
        key = (peer, delivery)
        if key not in self.drafts and len(self.drafts) >= GuiLimits.TEXT_CONTEXTS:
            return False
        size = sum(
            len(text.encode('utf-8')) for k, text in self.drafts.items() if k != key
        )
        if size + len(value.encode('utf-8')) > GuiLimits.TEXT_BYTES:
            return False
        if value:
            self.drafts[key] = value
        else:
            self.drafts.pop(key, None)
        return True

    def abandon(self) -> None:
        """Invalidates jobs and releases all profile-owned presentation references.

        Args:
            None
        Returns:
            None
        """
        self.generation += 1
        self.snapshot = None
        self.preferences = None
        self.capabilities = frozenset()
        self.drafts.clear()
        self.back_stack.clear()
        self.root_pages.clear()
        self.secondary_scroll.clear()
        self.route = Route()
        self.covered = True
        self.busy = False
        self.status = ''
