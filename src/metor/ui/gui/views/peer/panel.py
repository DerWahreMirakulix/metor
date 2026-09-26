"""Persistent peer pane with identity-preserving timeline and anchored input stage."""

from collections.abc import Callable
from functools import partial

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from metor.core.api import Delivery
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import Action, Label
from metor.ui.gui.widgets.symbol import IconAction
from metor.ui.gui.widgets.sheet import ActionSheet

# Local Package Imports
from .composer import Composer
from .timeline import Timeline
from ..actions import clear_drops, live_context_actions


class PeerView(BoxLayout):
    """Retains input and timeline ownership until its route or authorization changes."""

    def __init__(
        self, controller: GuiController, refresh: Callable[[], None], *, wide: bool
    ) -> None:
        """Creates stable native controls bound to one exact peer projection.

        Args:
            controller: Public-service presentation coordinator.
            refresh: Coalesced native repaint request.
            wide: Whether End Live belongs in the desktop header.
        Returns:
            None
        """
        super().__init__(orientation='vertical', spacing=dp(16))
        self.controller, self.refresh = controller, refresh
        self.route = controller.state.route
        header = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(12))
        self.header = header
        header.add_widget(IconAction('chevron-left', 'Back', self._back))
        heading = BoxLayout(orientation='vertical')
        self.name = Label('', role='peer', wrap=False)
        self.subtitle = Label('', role='caption', tone='textSecondary', wrap=False)
        heading.add_widget(self.name)
        heading.add_widget(self.subtitle)
        header.add_widget(heading)
        header.add_widget(IconAction('ellipsis', 'Conversation actions', self._menu))
        self._end_identity: tuple[int | None, str | None] | None = None
        self.end = Action(
            'End Live', partial(self._end_live, None, None), tone='danger'
        )
        self.end.size_hint_x = None
        self.end.width = dp(128)
        self.add_widget(header)
        tabs = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(4))
        for delivery in (Delivery.DROP, Delivery.LIVE):
            tabs.add_widget(
                Action(
                    delivery.value.upper(),
                    partial(self._tab, delivery),
                    surface=delivery.value + 'Surface'
                    if delivery is self.route.delivery
                    else 'surface',
                    tone=delivery.value,
                )
            )
        Action.group(tuple(reversed(tabs.children)))
        self.add_widget(tabs)
        self.controls = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(12))
        self.auto_play = Action('Auto-play: Off', self._toggle_auto)
        self.controls.add_widget(self.auto_play)
        self._end_parent = header if wide else self.controls
        self.timeline = Timeline(controller, self.route, refresh)
        self.add_widget(self.timeline)
        self.connect = Action(
            'Start Live', self._connect, surface='live', tone='onAccent'
        )
        self.status = Label('', role='support', tone='info')
        self.retry_recording: Action | None = None
        self._recovery_identity: tuple[int, str] | None = None
        self.composer = Composer(controller, self.route, refresh)
        self.update()

    def reflow(self, *, wide: bool) -> None:
        """Moves only the responsive action group while retaining focus, drafts and PTT widgets.

        Args:
            wide: Whether the available viewport includes the desktop master pane.
        Returns:
            None
        """
        destination = self.header if wide else self.controls
        if destination is not self._end_parent:
            if self.end.parent is not None:
                self.end.parent.remove_widget(self.end)
            self._end_parent = destination
        self.update()

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
                        'Clear Drops',
                        clear,
                        tone='danger',
                        disabled=controller.state.busy
                        or controller.drop.pending is not None,
                    )
                )
            if self.route.delivery is Delivery.LIVE:
                live_context_actions(
                    controller, peer, body, lambda: sheet.dismiss(animation=False)
                )

        sheet = ActionSheet(
            controller,
            build,
            title=lambda: controller.contacts.alias(peer),
            compact_menu=True,
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

    def _toggle_auto(self) -> None:
        """Changes the existing context override without playing old backlog.

        Args:
            None
        Returns:
            None
        """
        self.controller.playback.auto.toggle(self.route.peer or '')
        self.refresh()

    def _tab(self, delivery: Delivery) -> None:
        """Changes the projection with no implicit connect or consume action.

        Args:
            delivery: Deliberately selected peer projection.
        Returns:
            None
        """
        self.controller.navigate(
            Route(
                'V08' if delivery is Delivery.DROP else 'V09', self.route.peer, delivery
            )
        )
        self.refresh()

    def _connect(self) -> None:
        """Starts LIVE only in response to its explicit action.

        Args:
            None
        Returns:
            None
        """
        self.controller.live.start(self.route.peer or '')
        self.refresh()

    def _end_live(self, context_generation: int | None, attempt_id: str | None) -> None:
        """Finalizes the local press on its original target before requesting end.

        Args:
            context_generation: Logical context captured when this control was created.
            attempt_id: Calling attempt captured when this control was created.
        Returns:
            None
        """
        self.controller.live.end(self.route.peer or '', context_generation, attempt_id)
        self.refresh()

    def update(self) -> None:
        """Reconciles public data in place while retaining composer and scroll ownership.

        Args:
            None
        Returns:
            None
        """
        controller, state = self.controller, self.controller.state
        self.auto_play.label.text = (
            'Auto-play: On'
            if controller.playback.auto.enabled(self.route.peer or '')
            else 'Auto-play: Off'
        )
        peer, snapshot = self.route.peer, state.snapshot
        live = (
            next((item for item in snapshot.live_contexts if item.onion == peer), None)
            if snapshot
            else None
        )
        aliases = (
            [(item.onion, item.alias) for item in snapshot.contacts]
            + [(item.onion, item.alias) for item in snapshot.conversations]
            + [(item.onion, item.alias) for item in snapshot.live_contexts]
            if snapshot
            else []
        )
        alias = next((name for onion, name in aliases if onion == peer), 'Conversation')
        self.name.text = alias
        active = live is not None and (
            live.session_state == 'connected' or live.recovery_eligible
        )
        calling = bool(live and live.outbound_attempt_id and not active)
        identity = (
            live.context_generation if live and active else None,
            live.outbound_attempt_id if live and calling else None,
        )
        if identity != self._end_identity:
            if self.end.parent is not None:
                self.end.parent.remove_widget(self.end)
            self.end = Action(
                'Cancel' if calling else 'End Live',
                partial(self._end_live, *identity),
                tone='danger',
                size_hint_x=None,
                width=dp(128),
            )
            self._end_identity = identity
        self.subtitle.text = (
            'Drop conversation'
            if self.route.delivery is Delivery.DROP
            else 'Changing route…'
            if live and live.route_changing
            else 'Reconnecting…'
            if live and live.session_state != 'connected' and live.recovery_eligible
            else 'Connected · Live'
            if active
            else 'Calling…'
            if calling
            else 'Incoming Live request'
            if live and live.session_state == 'pending'
            else 'No Live connection'
        )
        if self.route.delivery is Delivery.LIVE:
            if active and self.auto_play.parent is None:
                self.controls.add_widget(
                    self.auto_play, index=len(self.controls.children)
                )
            elif not active and self.auto_play.parent is self.controls:
                self.controls.remove_widget(self.auto_play)
            show_controls = active or calling and self._end_parent is self.controls
            if show_controls and self.controls.parent is None:
                self.add_widget(self.controls, index=len(self.children) - 2)
            elif not show_controls and self.controls.parent is self:
                self.remove_widget(self.controls)
            if (active or calling) and self.end.parent is None:
                self._end_parent.add_widget(self.end)
            elif not (active or calling) and self.end.parent is not None:
                self.end.parent.remove_widget(self.end)
        self.end.disabled = self.connect.disabled = (
            state.busy
            or controller.client is None
            or controller.live.pending is not None
        )
        self.end.disabled = (
            self.end.disabled
            or 'qualified_live_control' not in state.capabilities
            or identity == (None, None)
        )
        self.connect.label.text = 'Reconnect' if live else 'Start Live'
        self.timeline.update(active=active)
        if (
            self.route.delivery is Delivery.LIVE
            and not active
            and not calling
            and (live is None or live.session_state == 'disconnected')
        ):
            if self.connect.parent is None:
                self.add_widget(self.connect)
        elif self.connect.parent is self:
            self.remove_widget(self.connect)
        self.status.text = state.status
        if state.status and self.status.parent is None:
            self.add_widget(self.status, index=1 if self.composer.parent is self else 0)
        elif not state.status and self.status.parent is self:
            self.remove_widget(self.status)
        if self.route.delivery is Delivery.DROP or active:
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
        elif self.retry_recording is not None and self.retry_recording.parent is self:
            self.remove_widget(self.retry_recording)
