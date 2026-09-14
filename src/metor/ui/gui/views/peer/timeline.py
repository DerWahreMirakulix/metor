"""Paged native timeline with stable identity, chronology and independent scroll position."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import partial

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView

from metor.core.api import (
    ContentType,
    Delivery,
    MessageDirectionCode,
    MessageStatusCode,
    TextContent,
    VoiceContent,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.platform.audio import PcmVoice
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import Action, Label
from metor.ui.gui.widgets.message import MessageBubble
from metor.ui.gui.widgets.voice import VoiceCard

# Local Package Imports
from ..actions import message_menu


@dataclass(frozen=True)
class TimelineRow:
    """One plain visible projection; contains no encoded media or storage reference."""

    direction: MessageDirectionCode
    msg_id: str
    order: int
    text: str | None
    metadata: str
    codec: str | None = None
    size: int = 0
    finalized: bool = True
    status: MessageStatusCode = MessageStatusCode.UNREAD

    @property
    def key(self) -> tuple[MessageDirectionCode, str]:
        """Returns a direction-qualified identity within the captured peer projection.

        Args:
            None
        Returns:
            tuple[MessageDirectionCode, str]: Stable row identity.
        """
        return self.direction, self.msg_id


def projection(controller: GuiController, route: Route) -> list[TimelineRow]:
    """Combines public archive and bounded same-runtime content without duplicating IDs.

    Args:
        controller: Current authorized GUI state.
        route: Exact foreground peer/projection.
    Returns:
        list[TimelineRow]: Stable chronological plain descriptors.
    """
    rows: dict[tuple[MessageDirectionCode, str], TimelineRow] = {}
    messages = controller.messages
    if messages is not None and messages.onion == route.peer:
        for order, item in enumerate(messages.messages, start=-len(messages.messages)):
            if item.delivery is not route.delivery or not item.msg_id:
                continue
            voice = item.content if isinstance(item.content, VoiceContent) else None
            row = TimelineRow(
                item.direction,
                item.msg_id,
                order,
                item.content.text if isinstance(item.content, TextContent) else None,
                item.timestamp + ' · ' + item.status.value.capitalize(),
                voice.codec if voice else None,
                voice.size_bytes if voice else 0,
                status=item.status,
            )
            rows[row.key] = row
    for entry in controller.transcript.items.values():
        if entry.peer != route.peer or entry.delivery is not route.delivery:
            continue
        if route.delivery is Delivery.DROP and controller.archive.before is not None:
            continue
        row = TimelineRow(
            entry.direction,
            entry.msg_id,
            entry.order,
            entry.text,
            'Recording interrupted'
            if entry.interrupted
            else entry.status.value.capitalize(),
            entry.codec,
            entry.size_bytes,
            entry.finalized,
            entry.status,
        )
        prior = rows.get(row.key)
        rows[row.key] = (
            replace(
                row, order=prior.order, metadata=entry.timestamp + ' · ' + row.metadata
            )
            if prior
            else row
        )
    inventory = controller.inventory.page
    if inventory is not None and controller.archive.before is None:
        for retained in inventory.messages:
            if retained.onion != route.peer or retained.delivery is not route.delivery:
                continue
            if retained.status is MessageStatusCode.DRAFT:
                continue
            key = retained.direction, retained.msg_id
            if key not in rows:
                rows[key] = TimelineRow(
                    *key,
                    len(rows),
                    None
                    if retained.content_type is ContentType.VOICE
                    else 'Pending text',
                    retained.status.value.capitalize(),
                    retained.codec,
                    retained.size_bytes,
                    retained.finalized,
                    retained.status,
                )
    if route.delivery is Delivery.LIVE:
        for turn in controller.voice.live_turns.values():
            if turn.binding.peer != route.peer:
                continue
            row = TimelineRow(
                MessageDirectionCode.OUT,
                turn.binding.msg_id,
                turn.order,
                None,
                'Queued as Drop'
                if turn.actual_delivery is Delivery.DROP
                else turn.status.value.capitalize()
                if turn.finalized
                else 'Recording…',
                PcmVoice.CODEC if turn.actual_delivery is Delivery.LIVE else None,
                turn.size_bytes,
                turn.finalized,
                turn.status,
            )
            rows[row.key] = row
    return sorted(rows.values(), key=lambda row: row.order)


class Timeline(BoxLayout):
    """Owns at most one native page while retaining scroll anchors by message identity."""

    def __init__(
        self, controller: GuiController, route: Route, refresh: Callable[[], None]
    ) -> None:
        """Creates the scroll viewport and separate page/new-item navigation controls.

        Args:
            controller: Public-service GUI coordinator.
            route: Captured peer projection.
            refresh: Coalesced native repaint request.
        Returns:
            None
        """
        super().__init__(orientation='vertical', spacing=dp(16))
        self.controller, self.route, self.refresh = controller, route, refresh
        self._widgets: dict[
            tuple[MessageDirectionCode, str], MessageBubble | VoiceCard
        ] = {}
        self._visible: list[tuple[MessageDirectionCode, str]] = []
        self._known: set[tuple[MessageDirectionCode, str]] = set()
        self._anchor: tuple[MessageDirectionCode, str] | None = None
        self._edge = True
        self._new_count = 0
        self._rows: list[TimelineRow] = []
        self.scroll = ScrollView(do_scroll_x=False)
        self.column = BoxLayout(
            orientation='vertical', spacing=dp(12), size_hint_y=None
        )
        self.column.bind(minimum_height=self.column.setter('height'))
        self.scroll.add_widget(self.column)
        self.scroll.bind(scroll_y=self._scroll_changed)
        self.add_widget(self.scroll)
        self.navigation = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        self.older = Action('Older', self._older)
        self.older.accessible_name = 'Older messages'
        self.newer = Action('Newer', self._newer)
        self.newer.accessible_name = 'Newer messages'
        self.retained = Action('More', self._retained)
        self.retained.accessible_name = 'More retained items'
        self.refresh_retained = Action('Refresh', self._refresh_retained)
        self.refresh_retained.accessible_name = 'Refresh retained items'
        self.new = Action(
            '', self._jump, size_hint_x=None, width=dp(160), pos_hint={'center_x': 0.5}
        )
        self.empty = Label('', role='support', tone='textSecondary')

    def _scroll_changed(self, _widget: object, value: float) -> None:
        """Captures an identity anchor when the user leaves the newest edge.

        Args:
            _widget: Native scroll source.
            value: Normalized position; zero denotes the bottom of this page.
        Returns:
            None
        """
        if value > 0 and self.column.height > self.scroll.height:
            self._edge = False
            if self._visible:
                self._anchor = self._visible[-1]
        elif self._visible and self._rows and self._visible[-1] == self._rows[-1].key:
            self._edge = True
            self._anchor = None
            self._new_count = 0

    def _older(self) -> None:
        """Moves to an older bounded page without reading or consuming media.

        Args:
            None
        Returns:
            None
        """
        keys = [row.key for row in self._rows]
        if self._visible and self._visible[0] in keys:
            index = keys.index(self._visible[0])
            if index:
                self._anchor = keys[index - 1]
                self._edge = False
                self.refresh()
                return
        if self.controller.archive.older():
            self._anchor = None
            self._edge = False
            self.refresh()

    def _retained(self) -> None:
        """Requests the next metadata page without reading or consuming its media.

        Args:
            None
        Returns:
            None
        """
        self.controller.inventory.more()
        self.refresh()

    def _refresh_retained(self) -> None:
        """Restarts an invalidated inventory using current authoritative facts.

        Args:
            None
        Returns:
            None
        """
        self.controller.inventory.reset()
        self.refresh()

    def _newer(self) -> None:
        """Moves one bounded page toward current content without forcing playback.

        Args:
            None
        Returns:
            None
        """
        if self.controller.archive.before is not None:
            self.controller.archive.reset()
            self._jump()
            return
        keys = [row.key for row in self._rows]
        if self._visible and self._visible[-1] in keys:
            index = min(
                len(keys) - 1, keys.index(self._visible[-1]) + GuiLimits.PAGE_ITEMS
            )
            self._anchor = keys[index] if index < len(keys) - 1 else None
            self._edge = self._anchor is None
            self.refresh()

    def _jump(self) -> None:
        """Restores the newest timeline position independently of audio playback.

        Args:
            None
        Returns:
            None
        """
        self._anchor = None
        self._edge = True
        self._new_count = 0
        self.refresh()

    def _settle(self, _elapsed: float) -> None:
        """Follows the edge only when the user had already chosen to follow it.

        Args:
            _elapsed: Native layout scheduling interval.
        Returns:
            None
        """
        if self._edge:
            self.scroll.scroll_y = 0

    def _menu(self, key: tuple[MessageDirectionCode, str]) -> None:
        """Opens actions for an immutable direction-qualified timeline item.

        Args:
            key: Originally displayed direction and message ID.
        Returns:
            None
        """

        def lookup() -> MessageStatusCode | None:
            """Resolves only the original target against the current public projection.

            Args:
                None
            Returns:
                MessageStatusCode | None: Current status, or unavailable.
            """
            return next(
                (
                    row.status
                    for row in projection(self.controller, self.route)
                    if row.key == key
                ),
                None,
            )

        message_menu(self.controller, self.route, *key, lookup)

    def update(self, *, active: bool) -> None:
        """Reconciles one bounded native page while updating existing widgets in place.

        Args:
            active: Whether the current peer has a usable LIVE context.
        Returns:
            None
        """
        rows = projection(self.controller, self.route)
        keys = [row.key for row in rows]
        incoming = set(keys) - self._known
        if not self._edge:
            self._new_count = min(GuiLimits.LIVE_ITEMS, self._new_count + len(incoming))
        self._known = set(keys)
        self._rows = rows
        end = keys.index(self._anchor) + 1 if self._anchor in keys else len(rows)
        selected = rows[max(0, end - GuiLimits.PAGE_ITEMS) : end]
        visible = [row.key for row in selected]
        for key in list(self._widgets):
            if key not in visible:
                self.column.remove_widget(self._widgets.pop(key))
        for row in selected:
            widget = self._widgets.get(row.key)
            if widget is None:
                if row.text is None:
                    target = self.controller.playback.target(
                        self.route.peer or '',
                        self.route.delivery,
                        row.direction,
                        row.msg_id,
                    )
                    if target is None:
                        continue
                    widget = VoiceCard(
                        self.controller,
                        target,
                        self.refresh,
                        partial(self._menu, row.key)
                        if self.route.delivery is Delivery.DROP
                        or row.direction is MessageDirectionCode.OUT
                        and row.status is MessageStatusCode.PENDING
                        else None,
                    )
                else:
                    widget = MessageBubble(
                        row.text,
                        row.metadata,
                        row.direction is MessageDirectionCode.IN,
                        self.route.delivery.value,
                        partial(self._menu, row.key)
                        if self.route.delivery is Delivery.DROP
                        or row.direction is MessageDirectionCode.OUT
                        and row.status is MessageStatusCode.PENDING
                        else None,
                    )
                self._widgets[row.key] = widget
            if isinstance(widget, VoiceCard):
                widget.update(row.size, row.finalized, row.codec, row.metadata)
            elif row.text is not None:
                widget.set_content(row.text, row.metadata)
        if visible != self._visible:
            desired = [
                self._widgets[key] for key in reversed(visible) if key in self._widgets
            ]
            for index, widget in enumerate(desired):
                if (
                    widget.parent is self.column
                    and self.column.children.index(widget) == index
                ):
                    continue
                if widget.parent is self.column:
                    self.column.remove_widget(widget)
                self.column.add_widget(widget, index=index)
            self._visible = visible
            Clock.schedule_once(self._settle, 0)
        if not selected:
            self.empty.text = (
                'No Drops yet'
                if self.route.delivery is Delivery.DROP
                else 'Live conversation'
                if active
                else 'No Live connection'
            )
            if self.empty.parent is None:
                self.column.add_widget(self.empty)
        elif self.empty.parent is self.column:
            self.column.remove_widget(self.empty)
        page = self.controller.messages
        archive_older = bool(page and page.onion == self.route.peer and page.has_older)
        inventory = self.controller.inventory.page
        self.newer.label.text = 'Latest' if self.controller.archive.before else 'Newer'
        for button, show in (
            (self.older, end > GuiLimits.PAGE_ITEMS or archive_older),
            (self.newer, end < len(rows) or self.controller.archive.before is not None),
            (self.retained, bool(inventory and inventory.next_cursor)),
            (self.refresh_retained, bool(self.controller.inventory.cursor)),
        ):
            if show and button.parent is None:
                self.navigation.add_widget(button)
            elif not show and button.parent is self.navigation:
                self.navigation.remove_widget(button)
        if self.navigation.children and self.navigation.parent is None:
            self.column.add_widget(self.navigation, index=len(self.column.children))
        elif not self.navigation.children and self.navigation.parent is self.column:
            self.column.remove_widget(self.navigation)
        if self._new_count > 0 and not self._edge:
            if self.new.parent is None:
                self.add_widget(self.new)
        elif self.new.parent is self:
            self.remove_widget(self.new)
        self.new.label.text = f'{self._new_count} new items ↓'
