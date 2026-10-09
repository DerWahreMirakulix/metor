"""One privacy-revocable native sheet with reachable actions and bounded scrolling content."""

from collections.abc import Callable
from typing import ClassVar

from kivy.clock import Clock
from kivy.core.text import Label as TextMeasure
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from metor.ui.gui.constants import Geometry
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.theme import color

# Local Package Imports
from .controls import Action, Label, Panel
from .layout import ActionRow
from .symbol import IconAction
from .tooltip import PointerTooltip


class ActionSheet(ModalView):
    """Owns one centered modal with privacy revocation and reachable actions."""

    current: ClassVar['ActionSheet | None'] = None

    def __init__(
        self,
        controller: GuiController,
        build: Callable[[BoxLayout], None],
        *,
        title: str | Callable[[], str] = 'Actions',
        primary: tuple[str, Callable[[], object]] | None = None,
        compact_menu: bool = False,
        rebuild_on_snapshot: bool = True,
        primary_tone: str = 'danger',
        footer: Label | None = None,
        revision: Callable[[], object] | None = None,
        snapshot_updates: bool = True,
        wrap_title: bool = True,
        stable_frame: bool = False,
        back: Callable[[], object] | None = None,
    ) -> None:
        """Creates current-state content with an explicit Close and persistent action area.

        Args:
            controller: Current GUI authorization and snapshot owner.
            build: Current-state content builder; aliases resolve at build time.
            title: Plain title or canonical current-label resolver.
            primary: Optional explicitly confirmed operation and its captured target.
            compact_menu: Applies the approved 320-unit maximum for contextual menus.
            rebuild_on_snapshot: False for immutable setting-key editors retaining input.
            primary_tone: Semantic primary label tone; confirmations default to danger.
            footer: Optional persistent scope/help text above the fixed actions.
            revision: Optional bounded local eligibility key for contextual actions.
            snapshot_updates: False for local configuration independent of Core snapshots.
            wrap_title: Measures full multi-line headings at the current text scale.
            stable_frame: Reserves available height so asynchronous content cannot move dismissal.
            back: Optional parent surface to open after a deliberate Back action.
        Returns:
            None
        """
        super().__init__(
            size_hint=(None, None),
            background_color=(*color('onAccent')[:3], 0.72),
            auto_dismiss=True,
        )
        self.controller, self.builder = controller, build
        self.heading, self.primary = title, primary
        self.compact_menu = compact_menu
        self.rebuild_on_snapshot = rebuild_on_snapshot
        self.snapshot_updates = snapshot_updates
        self.wrap_title = wrap_title
        self.stable_frame = stable_frame
        self.primary_tone = primary_tone
        self.footer = footer
        self._eligibility_revision = revision
        self._eligibility_key = revision() if revision else None
        self._keyboard_top = 0.0
        self._generation = controller.state.generation
        self._snapshot = id(controller.state.snapshot)
        self._busy = controller.state.busy
        self._disposed = False
        self.body = Panel(orientation='vertical', padding='24dp', spacing='16dp')
        self.add_widget(self.body)
        header = ActionRow(spacing='12dp')
        self.header = header
        self.title_label = Label(
            self.heading() if callable(self.heading) else self.heading,
            role='title',
            wrap=self.wrap_title,
        )
        self.title_viewport = ScrollView(
            do_scroll_x=False,
            do_scroll_y=False,
            size_hint_y=None,
            height=dp(Geometry.TARGET),
        )
        self.title_viewport.add_widget(self.title_label)
        header.add_widget(self.title_viewport)
        self.close_action = IconAction(
            'x', 'Close', self.dismiss, pos_hint={'center_y': 0.5}
        )
        header.add_widget(self.close_action)
        self.invitation_indicator = IconAction(
            'bell',
            'Pending Live invitations',
            self._open_invitation,
            tone='live',
            badge=True,
        )
        self._update_invitation_indicator()
        self.body.add_widget(header)
        self.scroll = ScrollView(do_scroll_x=False)
        self.column = BoxLayout(
            orientation='vertical', spacing='12dp', size_hint_y=None
        )
        self.column.bind(
            minimum_height=self.column.setter('height'), minimum_size=self._resize
        )
        self.scroll.add_widget(self.column)
        self.body.add_widget(self.scroll)
        if self.footer is not None:
            self.body.add_widget(self.footer)
        self.actions = ActionRow(spacing='12dp')
        self.cancel = Action('Cancel' if self.primary else 'Back', back or self.dismiss)
        self.actions.add_widget(self.cancel)
        self.primary_action: Action | None = None
        if self.primary:
            self.primary_action = Action(
                self.primary[0], self.primary[1], tone=self.primary_tone
            )
            self.actions.add_widget(self.primary_action)
        self.body.add_widget(self.actions)
        self.title_label.bind(height=self._resize)
        self.header.bind(height=self._resize)
        self.actions.bind(height=self._resize)
        self._build()
        self.bind(on_dismiss=self._dismissed)
        Window.bind(size=self._resize)
        if self.footer is not None:
            self.footer.bind(height=self._resize)

    def _build(self) -> None:
        """Refreshes current content while retaining ownership of dismissal gestures."""
        if self._disposed:
            return
        self._revoke_widgets(self.column)
        self.column.clear_widgets()
        self.title_label.text = (
            self.heading() if callable(self.heading) else self.heading
        )
        self.builder(self.column)
        self._resize()

    @staticmethod
    def _revoke_widgets(root: Widget) -> None:
        """Clears removed private content and cancels held input without activation."""
        for widget in root.walk(restrict=True):
            if isinstance(widget, Action):
                widget.cancel_input()
                widget.disabled = True
                widget.accessible_name = ''
            elif isinstance(widget, TextInput):
                widget.focus = False
                widget.disabled = True
            if isinstance(widget, (Label, TextInput)):
                widget.text = ''

    def _resize(self, *_args: object) -> None:
        """Measures action labels and keeps consequences scrollable above fixed controls.

        Args:
            _args: Native window/content geometry changes.
        Returns:
            None
        """
        if self._disposed:
            return
        self.width = min(dp(320 if self.compact_menu else 480), Window.width - dp(48))
        needed = self.actions.spacing
        if self.primary_action is not None:
            for action in (self.cancel, self.primary_action):
                label = TextMeasure(
                    text=action.label.text,
                    font_name=action.label.font_name,
                    font_size=action.label.font_size,
                )
                label.refresh()
                needed += label.texture.size[0] + action.padding[0] + action.padding[2]
        stacked = self.primary is not None and needed > self.width - dp(48)
        if self.primary and len(self.actions.children) == 2:
            correct = self.actions.children[0 if stacked else -1] is self.cancel
            if not correct:
                self.actions.remove_widget(self.cancel)
                self.actions.add_widget(
                    self.cancel, index=0 if stacked else len(self.actions.children)
                )
        self.actions.orientation = 'vertical' if stacked else 'horizontal'
        available = Window.height - self._bottom() - dp(Geometry.EDGE)
        fixed_height = (
            self.body.padding[1]
            + self.body.padding[3]
            + self.body.spacing * (len(self.body.children) - 1)
            + self.actions.height
            + (self.footer.height if self.footer is not None else 0)
        )
        self.title_viewport.height = min(
            max(dp(Geometry.TARGET), self.title_label.height),
            max(dp(Geometry.TARGET), available - fixed_height - dp(Geometry.TARGET)),
        )
        self.title_viewport.do_scroll_y = (
            self.title_label.height > self.title_viewport.height
        )
        desired_height = self.header.height + fixed_height + self.column.minimum_height
        self.height = available if self.stable_frame else min(available, desired_height)
        self.scroll.do_scroll_y = self.height < desired_height
        self._align_center()

    def _align_center(self, *_args: object) -> None:
        """Centers the modal within the space above the local keyboard.

        Args:
            _args: Native modal/window geometry callback.
        Returns:
            None
        """
        self.center_x = Window.center[0]
        self.center_y = (Window.height - dp(Geometry.EDGE) + self._bottom()) / 2

    def _bottom(self) -> float:
        """Keeps modal controls above a visible local keyboard with the approved gap.

        Args:
            None
        Returns:
            float: Window-coordinate bottom edge of the sheet.
        """
        return float(
            self._keyboard_top + dp(Geometry.KEYBOARD_GAP)
            if self._keyboard_top
            else dp(Geometry.EDGE)
        )

    def set_keyboard_top(self, top: float) -> None:
        """Reserves native modal space for its own focused field's local keyboard.

        Args:
            top: Visible keyboard top, or zero when dismissed.
        Returns:
            None
        """
        self._keyboard_top = top
        self._resize()

    def show(self) -> None:
        """Opens under current authorization and initially focuses safe dismissal.

        Args:
            None
        Returns:
            None
        """
        if self._disposed:
            return
        PointerTooltip.clear_all()
        if ActionSheet.current is not None:
            ActionSheet.current.dismiss(animation=False)
        if not self.controller.state.covered and not self._disposed:
            ActionSheet.current = self
            self.open(animation=False)
            Clock.schedule_once(self._focus_cancel, 0)

    def _focus_cancel(self, _elapsed: float) -> None:
        """Prevents opening a destructive confirmation from implicitly arming its operation.

        Args:
            _elapsed: Native scheduler interval.
        Returns:
            None
        """
        if ActionSheet.current is self and not any(
            bool(getattr(widget, 'focus', False))
            for widget in self.body.walk()
            if widget is not self.cancel
        ):
            self.cancel.focus = True

    def dismiss(self, *args: object, **kwargs: object) -> None:
        """Closes immediately so the next visible control can receive input.

        Args:
            args: Native dismissal callback arguments.
            kwargs: Native options; closing never retains a fading input surface.
        Returns:
            None.
        """
        kwargs['animation'] = False
        super().dismiss(*args, **kwargs)

    def _dismissed(self, *_args: object) -> None:
        """Releases old labels and the global modal reference immediately.

        Args:
            _args: Native dismissal event.
        Returns:
            None
        """
        self._disposed = True
        Window.unbind(size=self._resize)
        if self.footer is not None:
            self.footer.unbind(height=self._resize)
        self._revoke_widgets(self.body)
        self._revoke_widgets(self.invitation_indicator)
        self.heading = ''
        self.column.clear_widgets()
        self.body.clear_widgets()
        if ActionSheet.current is self:
            ActionSheet.current = None

    @classmethod
    def reconcile(cls) -> None:
        """Revokes private modals before a cover, or rebuilds current canonical labels.

        Args:
            None
        Returns:
            None
        """
        sheet = cls.current
        if sheet is None:
            return
        sheet._update_invitation_indicator()
        state = sheet.controller.state
        if state.covered or state.generation != sheet._generation:
            sheet.dismiss(animation=False)
        elif (
            sheet.snapshot_updates
            and sheet._snapshot != id(state.snapshot)
            or sheet._busy != state.busy
            or (
                sheet._eligibility_revision is not None
                and sheet._eligibility_key != sheet._eligibility_revision()
            )
        ):
            sheet._snapshot = id(state.snapshot)
            sheet._busy = state.busy
            sheet._eligibility_key = (
                sheet._eligibility_revision() if sheet._eligibility_revision else None
            )
            if sheet.primary_action is not None:
                sheet.primary_action.cancel_input()
            if sheet.rebuild_on_snapshot:
                sheet._build()
                if not sheet.close_action.focus:
                    sheet.cancel.focus = True

    def _update_invitation_indicator(self) -> None:
        """Makes incoming activity reachable above the native modal without stealing focus.

        Args:
            None
        Returns:
            None
        """
        visible = not self.compact_menu and bool(
            self.controller.live_invitations.pending_handles()
        )
        if visible and self.invitation_indicator.parent is None:
            self.header.add_widget(self.invitation_indicator, index=1)
        elif not visible and self.invitation_indicator.parent is not None:
            self.header.remove_widget(self.invitation_indicator)

    def _open_invitation(self) -> None:
        """Cancels this modal before the user's explicit switch to an incoming request.

        Args:
            None
        Returns:
            None
        """
        self.dismiss(animation=False)
        self.controller.live_invitations.show()


def confirm(
    controller: GuiController,
    title: str,
    explanation: str,
    action: Callable[[], object],
) -> None:
    """Presents a concrete local destructive action with a safely focused Cancel.

    Args:
        controller: Current authorization owner.
        title: Explicit confirmation action label.
        explanation: Plain scope and consequences.
        action: Exact captured operation; outside click and Enter on Cancel never commit.
    Returns:
        None
    """

    def build(body: BoxLayout) -> None:
        """Builds the destructive-action explanation inside the sheet.

        Args:
            body (BoxLayout): The body input.

        Returns:
            None
        """
        body.add_widget(Label(explanation, tone='textSecondary'))

    def accept() -> None:
        """Closes the sheet and runs the authorized action while uncovered.

        Args:
            None

        Returns:
            None
        """
        sheet.dismiss(animation=False)
        if not controller.state.covered:
            action()

    sheet = ActionSheet(controller, build, title=title, primary=(title, accept))
    sheet.show()
