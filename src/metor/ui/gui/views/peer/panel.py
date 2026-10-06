"""Persistent peer pane with identity-preserving timeline and anchored input stage."""

from collections.abc import Callable
from functools import partial

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from metor.core.api import Delivery
from metor.ui.gui.constants import Geometry
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import Action, Label
from metor.ui.gui.widgets.symbol import IconAction
from metor.ui.gui.widgets.sheet import ActionSheet

# Local Package Imports
from .composer import Composer
from .timeline import Timeline
from .header import LiveHeaderAction
from ..audio import show_audio_unavailable
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
            wide: Whether the surrounding viewport has a desktop master pane.
        Returns:
            None
        """
        super().__init__(orientation='vertical', spacing=dp(16))
        self.controller, self.refresh = controller, refresh
        self.route = controller.state.route
        self.header = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(8))
        self.header.bind(minimum_height=self.header.setter('height'))
        title_row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(12))
        title_row.add_widget(IconAction('chevron-left', 'Back', self._back))
        self.name = Label('', role='peer')
        self.name.bind(
            height=lambda _widget, height: setattr(
                title_row, 'height', max(dp(48), height)
            )
        )
        title_row.add_widget(self.name)
        self.header.add_widget(title_row)
        self.controls = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(12))
        self.subtitle = Label('', role='caption', tone='textSecondary')
        self.subtitle.bind(
            height=lambda _widget, height: setattr(
                self.controls, 'height', max(dp(48), height)
            )
        )
        self.controls.add_widget(self.subtitle)
        self.live_slot = BoxLayout(size_hint_x=None, width=dp(48))
        self.controls.add_widget(self.live_slot)
        self.call = IconAction('phone', 'Call', self._call)
        self.more = IconAction('ellipsis', 'Conversation actions', self._menu)
        self.controls.add_widget(self.call)
        self.controls.add_widget(self.more)
        self.header.add_widget(self.controls)
        self._end_identity: tuple[int | None, str | None] | None = None
        self.end = LiveHeaderAction(
            'End Live', 'x', partial(self._end_live, None, None), tone='danger'
        )
        self.connect = LiveHeaderAction(
            'Start Live', 'plus', self._connect, surface='live', tone='onAccent'
        )
        self.add_widget(self.header)
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
        self.timeline = Timeline(controller, self.route, refresh)
        self.add_widget(self.timeline)
        self.retry_recording: Action | None = None
        self._recovery_identity: tuple[int, str] | None = None
        self.composer = Composer(controller, self.route, refresh)
        self.bind(width=lambda *_args: self.update())
        self.update()

    def reflow(self, *, wide: bool) -> None:
        """Reflows visual action width while retaining header, focus, drafts and PTT ownership.

        Args:
            wide: Whether the available viewport includes the desktop master pane.
        Returns:
            None
        """
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

    def _call(self) -> None:
        """Requests a separately authorized telephone call without changing chat mode.

        Args:
            None
        Returns:
            None
        """
        if not self.controller.calls.ready:
            show_audio_unavailable(self.controller, self.refresh, purpose='calls')
        else:
            self.controller.calls.start(self.route.peer or '')
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
            attempt_id: Chat invitation attempt captured when this control was created.
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
        connecting = bool(live and live.outbound_attempt_id and not active)
        identity = (
            live.context_generation if live and active else None,
            live.outbound_attempt_id if live and connecting else None,
        )
        if identity != self._end_identity:
            if self.end.parent is not None:
                self.end.parent.remove_widget(self.end)
            self.end = LiveHeaderAction(
                'Cancel Live' if connecting else 'End Live',
                'x',
                partial(self._end_live, *identity),
                tone='danger',
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
            else 'Connecting chat…'
            if connecting
            else 'Incoming Live request'
            if live and live.session_state == 'pending'
            else 'No Live connection'
        )
        control: LiveHeaderAction | None
        if self.route.delivery is Delivery.LIVE:
            control = self.end if active or connecting else self.connect
            available = (
                active
                or connecting
                or live is None
                or live.session_state == 'disconnected'
            )
            if not available:
                control = None
        else:
            control = None
        for attached in tuple(self.live_slot.children):
            if attached is not control:
                self.live_slot.remove_widget(attached)
        if control is not None:
            if control.parent is None:
                self.live_slot.add_widget(control)
        else:
            self.live_slot.width = 0
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
        self.connect.label.text = self.connect.accessible_name = (
            'Reconnect Live' if live else 'Start Live'
        )
        self.call.disabled = state.busy
        if control is not None:
            control.present(compact=self.width < dp(Geometry.COMPACT_MAX))
            self.live_slot.width = control.width
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
