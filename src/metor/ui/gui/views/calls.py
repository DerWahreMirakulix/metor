"""Nonmodal incoming-call surface preserving underlying typing and PTT ownership."""

from collections.abc import Callable
from functools import partial

from kivy.metrics import dp, sp
from kivy.core.text import Label as CoreLabel
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.scrollview import ScrollView
from kivy.input.motionevent import MotionEvent

from metor.ui.gui.constants import Geometry
from metor.ui.gui.theme import font_path, TYPE
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Action, Label, Panel
from metor.ui.gui.widgets.symbol import IconAction
from metor.ui.gui.widgets.sheet import ActionSheet


class CallPanel(Panel):
    """Consumes touches inside its surface while leaving the surrounding view usable."""

    def on_touch_down(self, touch: MotionEvent) -> bool:
        """Prevents a call-surface press from activating obscured underlying controls.

        Args:
            touch: Native pointer event.
        Returns:
            bool: Whether this panel or one of its controls owns the press.
        """
        return bool(super().on_touch_down(touch) or self.collide_point(*touch.pos))


class CallOverlay(FloatLayout):
    """Paints call metadata without native modal focus grabs or unsolicited navigation."""

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
        self.bottom_inset = 0.0
        self.bind(size=lambda *_args: self.refresh())

    def render(self) -> None:
        """Reconciles only permitted call content, retaining stable controls between updates.

        Args:
            None
        Returns:
            None
        """
        calls = self.controller.calls
        state = self.controller.state
        modal = (
            ActionSheet.current is not None
            or self.controller.interactions.prompt is not None
        )
        key = (
            state.generation,
            state.covered,
            calls.revision,
            self.size[:],
            modal,
            self.bottom_inset,
        )
        if key == self._key:
            return
        self._key = key
        self.clear_widgets()
        entry = calls.entries.get(calls.selected or '')
        if entry is None:
            return
        if not calls.visible or modal:
            if not calls.visible and not any(
                item.phase != 'ended' for item in calls.entries.values()
            ):
                return
            indicator = Action(
                'Incoming Live',
                self._show,
                size_hint_x=None,
                width=dp(160),
                pos_hint={'right': 1, 'top': 1},
            )
            self.add_widget(indicator)
            return
        width = min(dp(480), self.width - dp(48))
        panel = CallPanel(
            orientation='vertical',
            padding=dp(24),
            spacing=dp(16),
            size_hint=(None, None),
            width=width,
        )
        header = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(12))
        title = Label('Incoming Live', role='title')
        title.bind(
            height=lambda _widget, height: setattr(
                header, 'height', max(dp(48), height)
            )
        )
        header.add_widget(title)
        header.add_widget(IconAction('x', 'Close call', self._dismiss))
        panel.add_widget(header)
        scroll = ScrollView(do_scroll_x=False)
        body = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(12))
        body.bind(minimum_height=body.setter('height'))
        if entry.label != 'Incoming Live':
            body.add_widget(Label(entry.label))
        body.add_widget(
            Label(
                'Accept keeps this view. Open switches to Live.',
                role='support',
                tone='textSecondary',
            )
        )
        if entry.status:
            body.add_widget(Label(entry.status, role='support', tone='textSecondary'))
        if len(calls.entries) > 1:
            pager = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(12))
            pager.add_widget(
                IconAction('chevron-left', 'Previous call', lambda: self._step(-1))
            )
            pager.add_widget(
                Label(
                    f'{list(calls.entries).index(entry.handle) + 1} of {len(calls.entries)}',
                    wrap=False,
                )
            )
            pager.add_widget(
                IconAction('chevron-right', 'Next call', lambda: self._step(1))
            )
            body.add_widget(pager)
        scroll.add_widget(body)
        panel.add_widget(scroll)
        button_size, _line, weight = TYPE['button']
        longest = CoreLabel(
            text='Unlock to accept' if entry.denied else 'Open Live',
            font_name=font_path(weight),
            font_size=sp(button_size),
        )
        longest.refresh()
        stacked = width - dp(48) < max(
            dp(360), 3 * (longest.texture.size[0] + dp(24)) + dp(24)
        )
        actions = BoxLayout(
            orientation='vertical' if stacked else 'horizontal',
            size_hint_y=None,
            height=dp(168 if stacked else 48),
            spacing=dp(12),
        )
        if entry.phase == 'ended':
            actions.height = dp(48)
            actions.add_widget(Action('Close', self._dismiss))
        else:
            for label, intent in (
                ('Decline', 'decline'),
                ('Unlock to accept' if entry.denied else 'Accept', 'accept'),
                ('Open Live', 'open'),
            ):
                handle = entry.handle
                action = Action(
                    label,
                    partial(self._perform, handle, intent),
                    disabled=state.busy
                    or (entry.phase != 'pending' and intent != 'open'),
                )
                actions.add_widget(action)
        panel.add_widget(actions)
        self.add_widget(panel)

        def measure(*_args: object) -> None:
            """Keeps scrollable content within the viewport with persistent call actions.

            Args:
                _args: Native layout updates.
            Returns:
                None
            """
            panel.height = min(
                self.height - dp(48) - self.bottom_inset,
                body.height + actions.height + header.height + dp(80),
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
        measure()

    def _show(self) -> None:
        """Switches from an explicitly dismissed modal to the current call surface.

        Args:
            None
        Returns:
            None
        """
        if self.controller.interactions.prompt is not None:
            return
        if ActionSheet.current is not None:
            ActionSheet.current.dismiss()
        self.controller.calls.show()
        self.refresh()

    def _dismiss(self) -> None:
        """Hides presentation without declining a call.

        Args:
            None
        Returns:
            None
        """
        self.controller.calls.dismiss()
        self.refresh()

    def _step(self, delta: int) -> None:
        """Selects another exact request without activating it.

        Args:
            delta: Signed Previous/Next displacement.
        Returns:
            None
        """
        self.controller.calls.step(delta)
        self.refresh()

    def _perform(self, handle: str, action: str) -> None:
        """Activates only the handle originally displayed by the pressed control.

        Args:
            handle: Bound per-client call identity.
            action: Explicit control intent.
        Returns:
            None
        """
        if action == 'accept':
            self.controller.calls.perform(handle, 'accept')
        elif action == 'decline':
            self.controller.calls.perform(handle, 'decline')
        elif action == 'open':
            self.controller.calls.perform(handle, 'open')
        self.refresh()
