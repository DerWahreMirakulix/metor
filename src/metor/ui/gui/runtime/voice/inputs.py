"""Native-input identity ownership independent of widget and profile lifetimes."""

from dataclasses import dataclass
from typing import Protocol
from metor.ui.gui.constants import GuiLimits

# Local Package Imports
from .press import PressSource


class PressSink(Protocol):
    """Semantic interaction target implemented by the current Voice controller."""

    def down(self, source: PressSource) -> bool: ...
    def up(self, source: PressSource) -> None: ...
    def depart(self, *, purge: bool = False) -> None: ...


@dataclass(frozen=True)
class HeldInput:
    """Binds an exact native release to the controller that observed its down."""

    identity: str
    sink: PressSink


class InputBridge:
    """Retains at most one input owner per registered channel across widget rebuilds."""

    def __init__(self) -> None:
        """Creates an inert three-channel native input boundary.

        Args:
            None
        Returns:
            None
        """
        self._held: dict[PressSource, HeldInput] = {}
        self._keys: set[str] = set()
        self._last_key: tuple[str, bool] | None = None

    def observe_key_down(self, identity: str) -> None:
        """Records physical key state before focused widgets receive the event.

        Args:
            identity: Native key code.
        Returns:
            None
        """
        fresh = identity not in self._keys and len(self._keys) < GuiLimits.HELD_KEYS
        if fresh:
            self._keys.add(identity)
        self._last_key = (identity, fresh)

    def fresh_key(self, identity: str) -> bool:
        """Rejects a held key that moved from another field into PTT focus.

        Args:
            identity: Current focused-key event identity.
        Returns:
            bool: Whether the window observed a fresh physical down.
        """
        return self._last_key == (identity, True)

    def observe_key_up(self, identity: str) -> bool:
        """Clears physical state and releases its original PTT owner, if any.

        Args:
            identity: Native released key code.
        Returns:
            bool: Whether a PTT press was released.
        """
        self._keys.discard(identity)
        self._last_key = None
        return self.up(PressSource.KEYBOARD, identity)

    def down(self, source: PressSource, identity: str, sink: PressSink) -> bool:
        """Binds a fresh physical identity before dispatching semantic PTT-down.

        Args:
            source: Registered pointer, focused-key or physical-button adapter.
            identity: Exact key/button/touch identity from the native event.
            sink: Current GUI interaction controller.
        Returns:
            bool: Whether one logical recording was admitted.
        """
        if source in self._held:
            return False
        self._held[source] = HeldInput(identity, sink)
        return sink.down(source)

    def up(self, source: PressSource, identity: str) -> bool:
        """Routes release to its original owner even after profile/view replacement.

        Args:
            source: Native release channel.
            identity: Verified native key/button/touch release identity.
        Returns:
            bool: Whether the release matched a retained input owner.
        """
        held = self._held.get(source)
        if held is None or held.identity != identity:
            return False
        self._held.pop(source)
        held.sink.up(source)
        return True

    def focus_lost(self) -> None:
        """Stops all owned recordings without inventing a physical release.

        Args:
            None
        Returns:
            None
        """
        for held in self._held.values():
            held.sink.depart()
