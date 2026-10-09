"""Nonmodal LIVE chat invitation surface preserving underlying typing and PTT ownership."""

from collections.abc import Callable
from functools import partial

from kivy.metrics import dp, sp
from kivy.core.text import Label as CoreLabel
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.input.motionevent import MotionEvent

from metor.ui.gui.constants import Geometry
from metor.ui.gui.theme import font_path, TYPE
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Action, ActionRow, Label, Panel
from metor.ui.gui.widgets.symbol import IconAction
from metor.ui.gui.widgets.sheet import ActionSheet


class InvitationPanel(Panel):
    """Consumes touches inside its surface while leaving the surrounding view usable."""

    def on_touch_down(self, touch: MotionEvent) -> bool:
        """Prevents an invitation-surface press from activating obscured underlying controls.

        Args:
            touch: Native pointer event.
        Returns:
            bool: Whether this panel or one of its controls owns the press.
        """
        return bool(super().on_touch_down(touch) or self.collide_point(*touch.pos))


class LiveInvitationOverlay(FloatLayout):
    """Paints invitation metadata without native modal focus grabs or unsolicited navigation."""

    def __init__(
        self, controller: GuiController, refresh: Callable[[], None], **kwargs: object
    ) -> None:
        """Creates an initially empty overlay in the application viewport.

        Args:
            controller: Public GUI service controller.
            refresh: Coalesced native repaint request.
            kwargs: Native overlay properties.
        Returns:
            None
        """
        super().__init__(**kwargs)
        self.controller = controller
        self.refresh = refresh
        self._key: tuple[object, ...] | None = None
        self._anchor: Widget | None = None
        self.bottom_inset = 0.0
        self.bind(size=lambda *_args: self.refresh())

    def anchor_to(self, anchor: Widget | None) -> None:
        """Positions the pending browser within its reserved activity row."""
        if anchor is self._anchor:
            return
        if self._anchor is not None:
            self._anchor.unbind(pos=self._anchor_changed, size=self._anchor_changed)
        self._anchor = anchor
        if anchor is not None:
            anchor.bind(pos=self._anchor_changed, size=self._anchor_changed)
        self.refresh()

    def _anchor_changed(self, *_args: object) -> None:
        """Schedules measured indicator placement after foreground layout changes."""
        self.refresh()

    def reserved_height(self) -> float:
        """Reserves a distinct activity row while the pending browser is discoverable."""
        invitations = self.controller.live_invitations
        if (
            self.controller.state.covered
            or invitations.visible
            or not invitations.pending_handles()
            or ActionSheet.current is not None
            or self.controller.interactions.prompt is not None
        ):
            return 0.0
        return self._indicator_size()[1]

    def _indicator_size(self) -> tuple[float, float]:
        """Measures the exact packaged font used by the pending browser's label."""
        text = (
            f'Pending Live · {len(self.controller.live_invitations.pending_handles())}'
        )
        button_size, _line, weight = TYPE['button']
        indicator_measure = CoreLabel(
            text=text,
            font_name=font_path(weight, text),
            font_size=sp(button_size),
        )
        indicator_measure.refresh()
        return (
            max(dp(160), indicator_measure.texture.size[0] + dp(24)),
            max(dp(Geometry.TARGET), indicator_measure.texture.size[1] + dp(16)),
        )

    def revoke(self) -> None:
        """Removes private invitation text and input ownership before a privacy cover."""
        for widget in self.walk(restrict=True):
            if isinstance(widget, Action):
                widget.cancel_input()
                widget.focus = False
        self.clear_widgets()
        self._key = None
        self.anchor_to(None)

    def render(self) -> None:
        """Reconciles only permitted invitation content, retaining stable controls between updates.

        Args:
            None
        Returns:
            None
        """
        invitations = self.controller.live_invitations
        state = self.controller.state
        anchor = self._anchor
        bounds = (
            (
                *self.to_widget(*anchor.to_window(*anchor.pos)),
                anchor.width,
                anchor.height,
            )
            if anchor is not None
            else (self.x, self.y, self.width, self.height)
        )
        modal = (
            ActionSheet.current is not None
            or self.controller.interactions.prompt is not None
        )
        key = (
            state.generation,
            state.covered,
            state.busy,
            invitations.revision,
            self.size[:],
            modal,
            self.bottom_inset,
            bounds,
        )
        if key == self._key:
            return
        self._key = key
        self.clear_widgets()
        if state.covered:
            return
        handles = invitations.pending_handles()
        if not handles or modal:
            return
        selected = (
            invitations.selected if invitations.selected in handles else handles[0]
        )
        entry = invitations.entries[selected]
        if not invitations.visible:
            left, bottom, available_width, available_height = bounds
            text = f'Pending Live · {len(handles)}'
            indicator_width, height = self._indicator_size()
            if available_height < height or available_width < dp(Geometry.TARGET):
                return
            indicator = Action(
                text,
                self._show,
                size_hint=(None, None),
                width=min(available_width, indicator_width),
            )
            indicator.height = height
            indicator.pos = (
                left + available_width - indicator.width,
                bottom + available_height - height,
            )
            self.add_widget(indicator)
            return
        width = min(dp(480), self.width - dp(48))
        compact = self.height - self.bottom_inset < dp(480)
        padding = dp(12 if compact else 24)
        spacing = dp(8 if compact else 16)
        panel = InvitationPanel(
            orientation='vertical',
            padding=padding,
            spacing=spacing,
            size_hint=(None, None),
            width=width,
        )
        header = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(12))
        title = Label(
            entry.label
            if compact
            else 'Accept Live chat?'
            if invitations.presentation == 'chooser'
            else 'Live chat invitation',
            role='row' if compact else 'title',
            wrap=not compact,
        )
        title.bind(
            height=lambda _widget, height: setattr(
                header, 'height', max(dp(48), height)
            )
        )
        header.add_widget(title)
        header.add_widget(IconAction('x', 'Close invitation', self._dismiss))
        panel.add_widget(header)
        scroll = ScrollView(do_scroll_x=False)
        body = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(12))
        body.bind(minimum_height=body.setter('height'))
        if entry.label != 'Live chat invitation' and not compact:
            body.add_widget(Label(entry.label))
        pager: BoxLayout | None = None
        if len(handles) > 1 and invitations.presentation == 'banner':
            pager = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(12))
            pager.add_widget(
                IconAction(
                    'chevron-left', 'Previous invitation', lambda: self._step(-1)
                )
            )
            pager.add_widget(
                Label(
                    f'{handles.index(entry.handle) + 1} of {len(handles)}',
                    wrap=False,
                )
            )
            pager.add_widget(
                IconAction('chevron-right', 'Next invitation', lambda: self._step(1))
            )
            if compact:
                body.add_widget(pager)
        if invitations.presentation == 'banner':
            body.add_widget(
                Label(
                    'Accept keeps your current view. Accept and open takes you to Live chat.',
                    role='support',
                    tone='textSecondary',
                )
            )
        if entry.status:
            body.add_widget(Label(entry.status, role='support', tone='textSecondary'))
        if pager is not None and not compact:
            body.add_widget(pager)
        scroll.add_widget(body)
        panel.add_widget(scroll)
        button_size, _line, weight = TYPE['button']
        longest = CoreLabel(
            text='Unlock to accept' if entry.denied else 'Accept and open',
            font_name=font_path(weight),
            font_size=sp(button_size),
        )
        longest.refresh()
        action_count = 2 if invitations.presentation == 'chooser' else 3
        stacked = width - padding * 2 < max(
            dp(360), action_count * (longest.texture.size[0] + dp(24)) + dp(24)
        )
        actions = ActionRow(
            orientation='vertical' if stacked else 'horizontal',
            spacing=dp(12),
        )
        choices = [
            ('Reject', 'decline'),
            ('Unlock to accept' if entry.denied else 'Accept', 'accept'),
        ]
        if invitations.presentation == 'banner':
            choices.append(('Accept and open', 'open'))
        for label, intent in choices:
            handle = entry.handle
            action = Action(
                label,
                partial(self._perform, handle, intent),
                disabled=state.busy or entry.phase != 'pending',
            )
            actions.add_widget(action)
        panel.add_widget(actions)
        self.add_widget(panel)

        def measure(*_args: object) -> None:
            """Keeps scrollable content within the viewport with persistent invitation actions.

            Args:
                _args: Native layout updates.
            Returns:
                None
            """
            panel.height = min(
                self.height - dp(48) - self.bottom_inset,
                body.height
                + actions.height
                + header.height
                + padding * 2
                + spacing * 2,
            )
            panel.x = self.x + (self.width - panel.width) / 2
            panel.y = (
                self.y
                + self.bottom_inset
                + (self.height - self.bottom_inset - panel.height) / 2
                if self.width >= dp(Geometry.BREAKPOINT)
                else self.y + dp(24) + self.bottom_inset
            )

        body.bind(height=measure)
        header.bind(height=measure)
        actions.bind(height=measure)
        measure()

    def _show(self) -> None:
        """Opens current pending requests through their explicit activity browser.

        Args:
            None
        Returns:
            None
        """
        if self.controller.interactions.prompt is not None:
            return
        if ActionSheet.current is not None:
            ActionSheet.current.dismiss()
        self.controller.live_invitations.show()
        self.refresh()

    def _dismiss(self) -> None:
        """Hides presentation without declining a invitation.

        Args:
            None
        Returns:
            None
        """
        self.controller.live_invitations.dismiss()
        self.refresh()

    def _step(self, delta: int) -> None:
        """Selects another exact request without activating it.

        Args:
            delta: Signed Previous/Next displacement.
        Returns:
            None
        """
        self.controller.live_invitations.step(delta)
        self.refresh()

    def _perform(self, handle: str, action: str) -> None:
        """Activates only the handle originally displayed by the pressed control.

        Args:
            handle: Bound per-client invitation identity.
            action: Explicit control intent.
        Returns:
            None
        """
        if action == 'accept':
            self.controller.live_invitations.perform(handle, 'accept')
        elif action == 'decline':
            self.controller.live_invitations.perform(handle, 'decline')
        elif action == 'open':
            self.controller.live_invitations.perform(handle, 'open')
        self.refresh()
