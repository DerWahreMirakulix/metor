"""Persistent peer pane with identity-preserving timeline and anchored input stage."""

from collections.abc import Callable
from functools import partial

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView

from metor.core.api import Delivery
from metor.ui.gui.constants import Geometry
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import Action, Label, TextField
from metor.ui.gui.widgets.symbol import IconAction
from metor.ui.gui.widgets.sheet import ActionSheet

# Local Package Imports
from .composer import Composer
from .timeline import Timeline
from .header import LiveHeaderAction, PeerHeader
from ..actions import call_peer, clear_drops, live_context_actions


class PeerView(BoxLayout):
    """Retains input and timeline ownership until its route or authorization changes."""

    def __init__(
        self, controller: GuiController, refresh: Callable[[], None], *, wide: bool
    ) -> None:
        """Creates stable native controls bound to one exact peer projection.

        Args:
            controller: Public-service presentation coordinator.
            refresh: Coalesced native repaint request.
            wide: Whether the surrounding viewport has a desktop master pane.
        Returns:
            None
        """
        super().__init__(orientation='vertical', spacing=dp(16))
        self.controller, self.refresh = controller, refresh
        self._revoked = False
        self.route = controller.state.route
        self.header = PeerHeader(
            controller,
            self.route,
            back=self._back,
            call=self._call,
            more=self._menu,
            start=self._connect,
            end=self._end_live,
        )
        self.header_viewport = ScrollView(
            do_scroll_x=False,
            do_scroll_y=False,
            size_hint_y=None,
            height=dp(Geometry.TARGET),
        )
        self.header_viewport.add_widget(self.header)
        self._header_geometry: tuple[float, float, bool, float] | None = None
        self._reveal_header = Clock.create_trigger(self._reveal_identity_row, 0)
        self.add_widget(self.header_viewport)
        self.timeline = Timeline(controller, self.route, refresh)
        self.add_widget(self.timeline)
        self.retry_recording: Action | None = None
        self._recovery_identity: tuple[int, str] | None = None
        self.composer = Composer(controller, self.route, self._refresh_connection)
        self.composer.bar.bind(minimum_height=self._measure_composer_bar)
        self.bind(height=self._measure_regions)
        self.bind(children=self._measure_regions)
        self.header.bind(height=self._measure_regions)
        self.composer.bind(height=self._measure_regions, parent=self._measure_regions)
        self.bind(width=lambda *_args: self.update())
        self.update()

    def _measure_composer_bar(self, *_args: object) -> None:
        """Reserves the real height of a wrapped PTT or send control within the input row."""
        self.composer.bar.height = max(dp(64), self.composer.bar.minimum_height)

    def _measure_regions(self, *_args: object) -> None:
        """Bounds the identity area while reserving readable history and input controls."""
        if self._revoked:
            return
        composer_height = sum(
            child.height
            for child in self.children
            if child not in (self.header_viewport, self.timeline)
        )
        self.spacing = dp(
            8
            if self.header.height
            + composer_height
            + dp(Geometry.TARGET)
            + dp(16) * (len(self.children) - 1)
            > self.height
            else 16
        )
        available = (
            self.height
            - composer_height
            - self.spacing * (len(self.children) - 1)
            - dp(Geometry.TARGET)
        )
        self.header_viewport.height = min(
            self.header.height, max(dp(Geometry.TARGET), available)
        )
        self.header_viewport.do_scroll_y = (
            self.header.height > self.header_viewport.height
        )
        if self.header_viewport.do_scroll_y:
            geometry = (
                self.header_viewport.height,
                self.header.height,
                self.header.expanded_title,
                self.header.call.height,
            )
            if geometry != self._header_geometry:
                self._header_geometry = geometry
                self._reveal_header()
        else:
            self._header_geometry = None
            self._reveal_header.cancel()

    def _reveal_identity_row(self, *_args: object) -> None:
        """Initially reveals complete identity actions after constrained layout settles."""
        if self._revoked or not self.header_viewport.do_scroll_y:
            return
        self.header_viewport.update_from_scroll()
        self.header_viewport.scroll_to(self.header.call, padding=0, animate=False)

    @property
    def name(self) -> Label:
        """Exposes the current peer title owned by the measured header."""
        return self.header.name

    @property
    def subtitle(self) -> Label:
        """Exposes the current connection status beside its explicit control."""
        return self.header.subtitle

    @property
    def call(self) -> IconAction:
        """Exposes the deliberate telephone action beside the peer title."""
        return self.header.call

    @property
    def more(self) -> IconAction:
        """Exposes the conversation menu beside the peer title."""
        return self.header.more

    @property
    def connect(self) -> LiveHeaderAction:
        """Exposes this peer's explicit Start or Open Live action."""
        return self.header.connect

    @property
    def end(self) -> LiveHeaderAction:
        """Exposes the currently qualified Cancel or End Live action."""
        return self.header.end

    def reflow(self, *, wide: bool) -> None:
        """Reflows visual action width while retaining header, focus, drafts and PTT ownership.

        Args:
            wide: Whether the available viewport includes the desktop master pane.
        Returns:
            None
        """
        if self._revoked:
            return
        self.composer.disabled = False
        self.update()
        self.disabled = False

    def suspend(self) -> None:
        """Revokes native interaction while retaining this peer projection's widgets."""
        self.composer.suspend()
        for widget in self.walk(restrict=True):
            if isinstance(widget, Action):
                widget.cancel_input()
            elif isinstance(widget, TextField):
                widget.focus = False
        self.disabled = True

    def revoke(self) -> None:
        """Synchronously clears discarded native content without a transport command."""
        if self._revoked:
            return
        self._revoked = True
        self.suspend()
        self.composer.revoke()
        for widget in self.walk(restrict=True):
            if isinstance(widget, Label):
                widget.text = ''
            if isinstance(widget, Action):
                widget.accessible_name = ''
        self.timeline.revoke()
        self.clear_widgets()

    def _menu(self) -> None:
        """Offers explicit actions on this pane's captured canonical peer.

        Args:
            None
        Returns:
            None
        """
        controller, peer = self.controller, self.route.peer or ''

        def build(body: BoxLayout) -> None:
            """Revalidates current permission and contact membership for the open menu.

            Args:
                body: Current scrolling menu body.
            Returns:
                None
            """

            def clear() -> None:
                """Opens a separate local DROP-only confirmation.

                Args:
                    None
                Returns:
                    None
                """
                sheet.dismiss(animation=False)
                clear_drops(controller, peer)

            def save() -> None:
                """Promotes this exact peer through the existing Save-only form.

                Args:
                    None
                Returns:
                    None
                """
                sheet.dismiss(animation=False)
                controller.contacts.begin('save', peer)
                self.refresh()

            snapshot = controller.state.snapshot
            saved = bool(
                snapshot
                and any(item.onion == peer and item.saved for item in snapshot.contacts)
            )
            if not saved:
                body.add_widget(
                    Action('Save contact', save, disabled=controller.state.busy)
                )
            if self.route.delivery is Delivery.DROP:
                body.add_widget(
                    Action(
                        'Delete conversation',
                        clear,
                        tone='danger',
                        disabled=controller.state.busy
                        or controller.drop.pending is not None
                        or not controller.drop.can_clear(peer),
                    )
                )
            if self.route.delivery is Delivery.LIVE:
                live_context_actions(
                    controller,
                    peer,
                    body,
                    lambda: sheet.dismiss(animation=False),
                    self._refresh_connection,
                    primary_controls=False,
                )

        sheet = ActionSheet(
            controller,
            build,
            title=lambda: controller.contacts.alias(peer),
            compact_menu=True,
            revision=lambda: controller.drop.can_clear(peer),
        )
        sheet.show()

    def _back(self) -> None:
        """Returns to the originating view without ending communication.

        Args:
            None
        Returns:
            None
        """
        self.controller.back()
        self.refresh()

    def _call(self) -> None:
        """Requests a separately authorized telephone call without changing chat mode.

        Args:
            None
        Returns:
            None
        """
        call_peer(self.controller, self.route.peer or '', self.refresh)

    def _connect(self) -> None:
        """Starts LIVE only in response to its explicit action.

        Args:
            None
        Returns:
            None
        """
        if self.controller.live.start(self.route.peer or ''):
            destination = Route('V09', self.route.peer, Delivery.LIVE)
            if self.controller.state.route != destination:
                self.controller.navigate(destination)
        self._refresh_connection()

    def _end_live(self, context_generation: int | None, attempt_id: str | None) -> None:
        """Finalizes the local press on its original target before requesting end.

        Args:
            context_generation: Logical context captured when this control was created.
            attempt_id: Chat invitation attempt captured when this control was created.
        Returns:
            None
        """
        self.controller.live.end(self.route.peer or '', context_generation, attempt_id)
        self._refresh_connection()

    def _refresh_connection(self) -> None:
        """Publishes control feedback synchronously before requesting the wider repaint."""
        self._update_connection()
        self.refresh()

    def _update_connection(self) -> bool:
        """Projects current connection state through this route's measured header."""
        return self.header.update()

    def update(self) -> None:
        """Reconciles public data in place while retaining composer and scroll ownership."""
        if self._revoked:
            return
        controller, state = self.controller, self.controller.state
        peer, snapshot = self.route.peer, state.snapshot
        aliases = (
            [(item.onion, item.alias) for item in snapshot.contacts]
            + [(item.onion, item.alias) for item in snapshot.conversations]
            + [(item.onion, item.alias) for item in snapshot.live_contexts]
            if snapshot
            else []
        )
        alias = next((name for onion, name in aliases if onion == peer), 'Conversation')
        self.name.text = alias
        active = self._update_connection()
        self.timeline.update(active=active)
        draft_owned = bool(
            peer in controller.voice.reviews
            and controller.voice.reviews[peer or ''].binding.delivery
            is self.route.delivery
        )
        recording_owned = bool(
            controller.voice.press.binding
            and controller.voice.press.binding.peer == peer
            and controller.voice.press.binding.delivery is self.route.delivery
        )
        if (
            self.route.delivery is Delivery.DROP
            or active
            or draft_owned
            or recording_owned
            or self.composer.has_pending_footer()
        ):
            if self.composer.parent is None:
                self.add_widget(self.composer)
            self.composer.update()
        elif self.composer.parent is self:
            self.remove_widget(self.composer)
        binding = controller.voice.press.binding
        failed = (
            binding is not None
            and binding.peer == self.route.peer
            and binding.delivery is self.route.delivery
            and controller.voice.press.phase.value == 'failed'
        )
        if failed and binding is not None:
            recovery_identity = (binding.generation, binding.msg_id)
            if recovery_identity != self._recovery_identity:
                if self.retry_recording is not None and self.retry_recording.parent:
                    self.remove_widget(self.retry_recording)
                self.retry_recording = Action(
                    'Retry finalization',
                    partial(controller.voice.recovery.retry, binding),
                )
                self._recovery_identity = recovery_identity
            if self.retry_recording is not None:
                if self.retry_recording.parent is None:
                    self.add_widget(self.retry_recording)
                self.retry_recording.disabled = (
                    state.busy
                    or controller.voice.running
                    or controller.voice.recovery.pending is not None
                )
        else:
            page = controller.inventory.page
            interrupted = (
                next(
                    (
                        item
                        for item in page.messages
                        if item.onion == peer
                        and item.delivery is self.route.delivery
                        and item.producer_interrupted
                        and item.can_retry_finalization
                    ),
                    None,
                )
                if page is not None and peer not in controller.voice.reviews
                else None
            )
            if interrupted is not None:
                identity = (state.generation, interrupted.msg_id)
                if identity != self._recovery_identity:
                    if self.retry_recording is not None and self.retry_recording.parent:
                        self.remove_widget(self.retry_recording)
                    self.retry_recording = Action(
                        'Review interrupted recording',
                        partial(controller.voice.recovery.claim, interrupted),
                    )
                    self._recovery_identity = identity
                assert self.retry_recording is not None
                if self.retry_recording.parent is None:
                    self.add_widget(self.retry_recording)
                self.retry_recording.disabled = (
                    state.busy
                    or controller.voice.running
                    or controller.voice.recovery.pending is not None
                )
            elif (
                self.retry_recording is not None and self.retry_recording.parent is self
            ):
                self.remove_widget(self.retry_recording)
