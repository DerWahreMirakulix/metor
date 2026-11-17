"""Measured persistent Call controls that reopen only the displayed telephone identity."""

from collections.abc import Callable
import time

from kivy.metrics import dp

from metor.core.api import CallInfo, CallState, NotificationPrivacy
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Action, ActionRow, Label, Panel
from metor.ui.gui.widgets.symbol import IconAction


class CallBar(Panel):
    """Reserves app chrome for an ongoing call without obscuring chat or settings."""

    def __init__(
        self, controller: GuiController, refresh: Callable[[], None], **kwargs: object
    ) -> None:
        """Creates hidden, inert controls; rendering never accepts or starts a call."""
        super().__init__(
            surface='liveSurface',
            orientation='vertical',
            size_hint_y=None,
            height=0,
            padding=(0.0, 0.0),
            **kwargs,
        )
        self.controller, self.refresh = controller, refresh
        self._key: tuple[object, ...] | None = None
        self._open: Action | None = None
        self._base = ''
        self.bind(width=lambda *_args: self.refresh())

    def revoke(self) -> None:
        """Clears caller text and stale input before a privacy cover returns."""
        for widget in self.walk(restrict=True):
            if isinstance(widget, Action):
                widget.cancel_input()
                widget.focus = False
                widget.disabled = True
                widget.accessible_name = ''
            if isinstance(widget, Label):
                widget.text = ''
        self.clear_widgets()
        self._open = None
        self._base = ''
        self._key = None
        self.padding = (0.0, 0.0)
        self.height = 0

    def _title(self, current: CallInfo) -> str:
        """Projects caller identity only under the current lock-notification policy."""
        state = self.controller.state
        privacy = self.controller.security.notification_privacy
        alias = current.alias
        if not state.covered and state.snapshot is not None:
            snapshot = state.snapshot
            alias = next(
                (
                    item.alias
                    for items in (
                        snapshot.contacts,
                        snapshot.conversations,
                        snapshot.live_contexts,
                    )
                    for item in items
                    if item.onion == current.peer
                ),
                alias,
            )
        visible_alias = (
            alias
            if not state.covered or privacy is NotificationPrivacy.SHOW_ALL
            else ''
        )
        if current.state is CallState.ACTIVE:
            if (
                not state.covered
                and state.route.view in {'V08', 'V09'}
                and state.route.peer == current.peer
            ):
                return 'Call in progress'
            return f'Call with {visible_alias}' if visible_alias else 'Call in progress'
        if current.state is CallState.INCOMING:
            return (
                f'Incoming call from {visible_alias}'
                if visible_alias
                else 'Incoming call'
            )
        return f'Calling {visible_alias}…' if visible_alias else 'Calling…'

    def render(self) -> None:
        """Updates the truthful timer in place and rebuilds only changed Call controls."""
        controller, calls = self.controller, self.controller.calls
        state, current = controller.state, calls.current
        visible = current is not None and current.state is not CallState.ENDED
        if (
            visible
            and current is not None
            and current.state is CallState.INCOMING
            and state.covered
            and controller.security.notification_privacy is NotificationPrivacy.OFF
        ):
            visible = False
        base = self._title(current) if visible and current is not None else ''
        key = (
            state.generation,
            state.covered,
            state.busy,
            (current.call_id, current.state, current.owned, current.muted)
            if visible and current is not None
            else None,
            controller.security.notification_privacy,
            base,
            self.width,
        )
        if key != self._key:
            self.revoke()
            self._key = key
            if not visible or current is None:
                return
            self._base = base
            self.padding = (dp(12), dp(8))
            row = ActionRow(spacing=dp(8))
            generation, call_id = state.generation, current.call_id

            def act(
                action: Callable[[], object],
                *,
                media: bool = False,
                muted: bool | None = None,
            ) -> None:
                """Checks the displayed identity before opening or mutating its exact call."""
                source = calls.current
                if (
                    controller.state.generation != generation
                    or source is None
                    or source.call_id != call_id
                    or source.state is CallState.ENDED
                    or media
                    and (not source.owned or source.state is not CallState.ACTIVE)
                    or muted is not None
                    and source.muted is not muted
                ):
                    return
                action()
                self.refresh()

            self._open = Action(base, lambda: act(lambda: calls.show(call_id)))
            self._open.accessible_name = 'Open call controls · ' + base
            row.add_widget(self._open)
            if current.owned and current.state is CallState.ACTIVE:
                row.add_widget(
                    IconAction(
                        'mic-off' if current.muted else 'mic',
                        'Unmute microphone' if current.muted else 'Mute microphone',
                        lambda: act(calls.mute, media=True, muted=current.muted),
                        disabled=state.busy,
                        pos_hint={'center_y': 0.5},
                    )
                )
                row.add_widget(
                    IconAction(
                        'phone',
                        'Hang up',
                        lambda: act(calls.end, media=True),
                        tone='danger',
                        disabled=state.busy,
                        pos_hint={'center_y': 0.5},
                    )
                )
            self.add_widget(row)

            def measure(*_args: object) -> None:
                """Reserves wrapped labels and minimum targets above the actual shell."""
                self.height = row.height + dp(16)

            row.bind(height=measure)
            measure()
        if self._open is not None and current is not None:
            seconds = (
                max(0, int(time.time() - current.started_at))
                if current.state is CallState.ACTIVE and current.started_at is not None
                else None
            )
            text = self._base + (
                f' · {seconds // 60:02d}:{seconds % 60:02d}'
                if seconds is not None
                else ''
            )
            self._open.label.text = text
            self._open.accessible_name = 'Open call controls · ' + text
