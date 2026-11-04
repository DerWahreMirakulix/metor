"""Bounded immutable accessibility projections and revocable native action admission."""

from collections import deque
from dataclasses import dataclass
from enum import Enum
import math
import threading

from metor.ui.gui.constants import GuiLimits


class AccessibleRole(str, Enum):
    """Roles exposed by the current native widget set."""

    LABEL = 'label'
    BUTTON = 'button'
    TEXT = 'text'
    PASSWORD = 'password'


class AccessibleAction(str, Enum):
    """Finite requests; physical hold-to-talk is never synthesized by Click."""

    FOCUS = 'focus'
    CLICK = 'click'
    SET_VALUE = 'set_value'


@dataclass(frozen=True)
class AccessibleNode:
    """One visible control; passwords carry neither value nor character count."""

    identity: int
    role: AccessibleRole
    name: str
    bounds: tuple[float, float, float, float]
    value: str | None = None
    enabled: bool = True
    focusable: bool = False
    clickable: bool = False
    editable: bool = False
    readonly: bool = False


@dataclass(frozen=True)
class AccessibleSnapshot:
    """One visible reading-order tree without toolkit objects or profile handles."""

    nodes: tuple[AccessibleNode, ...] = ()
    focus: int = 0
    width: float = 0
    height: float = 0


@dataclass(frozen=True)
class AccessibleRequest:
    """One bounded assistive-technology request tied to an exact presentation epoch."""

    epoch: int
    target: int
    action: AccessibleAction
    value: str | None = None


class AccessibleState:
    """Retains one native projection and a finite queue; revocation forgets both."""

    def __init__(self) -> None:
        """Creates an empty, content-free tree before any native adapter activation.

        Args:
            None
        Returns:
            None
        """
        self._lock = threading.Lock()
        self._snapshot = AccessibleSnapshot()
        self._epoch = 0
        self._nodes: dict[int, AccessibleNode] = {}
        self._requests: deque[AccessibleRequest] = deque()
        self._request_bytes = 0

    def read(self) -> AccessibleSnapshot:
        """Returns immutable data to native callback threads without accessing widgets.

        Args:
            None
        Returns:
            AccessibleSnapshot: Current safe projection.
        """
        with self._lock:
            return self._snapshot

    def publish(self, snapshot: AccessibleSnapshot) -> bool:
        """Validates finite projection ownership before replacing the native snapshot.

        Args:
            snapshot: UI-thread-authored visible tree.
        Returns:
            bool: Whether any exposed value or focus changed.
        """
        identities = {node.identity for node in snapshot.nodes}
        if (
            not all(
                math.isfinite(value) and value >= 0
                for value in (snapshot.width, snapshot.height)
            )
            or any(
                not all(math.isfinite(value) for value in node.bounds)
                or node.bounds[2] < node.bounds[0]
                or node.bounds[3] < node.bounds[1]
                for node in snapshot.nodes
            )
            or len(snapshot.nodes) > GuiLimits.ACCESSIBILITY_NODES
            or len(identities) != len(snapshot.nodes)
            or any(identity <= 0 for identity in identities)
            or snapshot.focus != 0
            and snapshot.focus not in identities
            or any(
                node.role is AccessibleRole.PASSWORD and node.value is not None
                for node in snapshot.nodes
            )
            or sum(
                len((node.name + (node.value or '')).encode('utf-8'))
                for node in snapshot.nodes
            )
            > GuiLimits.ACCESSIBILITY_BYTES
        ):
            raise ValueError('Invalid or excessive accessibility projection')
        with self._lock:
            if snapshot == self._snapshot:
                return False
            self._snapshot = snapshot
            self._nodes = {node.identity: node for node in snapshot.nodes}
            return True

    def revoke(self) -> None:
        """Drops private nodes and queued requests before a privacy transition returns.

        Args:
            None
        Returns:
            None
        """
        with self._lock:
            self._epoch += 1
            self._snapshot = AccessibleSnapshot()
            self._nodes.clear()
            self._requests.clear()
            self._request_bytes = 0

    def request(
        self, target: int, action: AccessibleAction, value: str | None = None
    ) -> bool:
        """Admits only advertised operations on a still-exposed exact control.

        Args:
            target: Native node identity, never a reused index or mutable alias.
            action: Requested semantic operation.
            value: Optional nonsecret editor replacement; never a password value.
        Returns:
            bool: Whether the bounded request was accepted for UI-thread rechecking.
        """
        if value is not None and len(value) > GuiLimits.TEXT_BYTES:
            return False
        size = len(value.encode('utf-8')) if value is not None else 0
        with self._lock:
            node = self._nodes.get(target)
            if (
                node is None
                or not node.enabled
                or action is AccessibleAction.FOCUS
                and not node.focusable
                or action is AccessibleAction.CLICK
                and not node.clickable
                or action is AccessibleAction.SET_VALUE
                and (
                    not node.editable
                    or node.role is AccessibleRole.PASSWORD
                    or value is None
                )
                or action is not AccessibleAction.SET_VALUE
                and value is not None
                or len(self._requests) >= GuiLimits.ACCESSIBILITY_ACTIONS
                or self._request_bytes + size > GuiLimits.TEXT_BYTES
            ):
                return False
            self._requests.append(AccessibleRequest(self._epoch, target, action, value))
            self._request_bytes += size
            return True

    def take(self) -> AccessibleRequest | None:
        """Transfers one request to the UI owner without invoking a widget off-thread.

        Args:
            None
        Returns:
            AccessibleRequest | None: Next request, or no pending action.
        """
        with self._lock:
            if not self._requests:
                return None
            request = self._requests.popleft()
            self._request_bytes -= (
                len(request.value.encode('utf-8')) if request.value else 0
            )
            return request if request.epoch == self._epoch else None
