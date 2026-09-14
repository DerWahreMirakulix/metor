"""One privacy-revocable native sheet with reachable actions and bounded scrolling content."""

from collections.abc import Callable
from typing import ClassVar

from kivy.clock import Clock
from kivy.core.text import Label as TextMeasure
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView

from metor.ui.gui.constants import Geometry
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.theme import color, font_path

# Local Package Imports
from .controls import Action, Label, Panel
from .symbol import IconAction


class ActionSheet(ModalView):
    """Owns one modal; the narrow presentation is bottom anchored and privacy revocable."""

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
        self.primary_tone = primary_tone
        self.footer = footer
        self._eligibility_revision = revision
        self._eligibility_key = revision() if revision else None
        self._keyboard_top = 0.0
        self._generation = controller.state.generation
        self._snapshot = id(controller.state.snapshot)
        self.body = Panel(orientation='vertical', padding=dp(24), spacing=dp(16))
        self.add_widget(self.body)
        self.column = BoxLayout()
        self.actions = BoxLayout()
        self.cancel = Action('Cancel' if primary else 'Back', self.dismiss)
        self._build()
        self.bind(on_dismiss=self._dismissed)
        Window.bind(size=self._resize)
        if self.footer is not None:
            self.footer.bind(height=self._resize)

    def _build(self) -> None:
        """Rebuilds current labels after a canonical contact/state change.

        Args:
            None
        Returns:
            None
        """
        self.body.clear_widgets()
        header = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(12))
        header.add_widget(
            Label(
                self.heading() if callable(self.heading) else self.heading,
                role='title',
                wrap=False,
            )
        )
        header.add_widget(IconAction('x', 'Close', self.dismiss))
        self.header = header
        self.call_indicator = IconAction(
            'bell', 'Incoming Live', self._open_call, tone='live', badge=True
        )
        self._update_call_indicator()
        self.body.add_widget(header)
        scroll = ScrollView(do_scroll_x=False)
        self.column = BoxLayout(
            orientation='vertical', spacing=dp(12), size_hint_y=None
        )
        self.column.bind(
            minimum_height=self.column.setter('height'), minimum_size=self._resize
        )
        self.builder(self.column)
        scroll.add_widget(self.column)
        self.body.add_widget(scroll)
        if self.footer is not None:
            self.body.add_widget(self.footer)
        self.actions = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(12))
        self.cancel = Action('Cancel' if self.primary else 'Back', self.dismiss)
        self.actions.add_widget(self.cancel)
        if self.primary:
            self.actions.add_widget(
                Action(self.primary[0], self.primary[1], tone=self.primary_tone)
            )
        self.body.add_widget(self.actions)
        self._resize()

    def _resize(self, *_args: object) -> None:
        """Measures action labels and keeps consequences scrollable above fixed controls.

        Args:
            _args: Native window/content geometry changes.
        Returns:
            None
        """
        self.width = min(dp(320 if self.compact_menu else 480), Window.width - dp(48))
        needed = dp(12 + 4 * 12)
        if self.primary:
            for text in ('Cancel', self.primary[0]):
                label = TextMeasure(
                    text=text, font_name=font_path(600), font_size=sp(14)
                )
                label.refresh()
                needed += label.texture.size[0]
        stacked = self.primary is not None and needed > self.width - dp(48)
        if self.primary and len(self.actions.children) == 2:
            correct = self.actions.children[0 if stacked else -1] is self.cancel
            if not correct:
                self.actions.remove_widget(self.cancel)
                self.actions.add_widget(
                    self.cancel, index=0 if stacked else len(self.actions.children)
                )
        self.actions.orientation = 'vertical' if stacked else 'horizontal'
        self.actions.height = dp(108 if stacked else 48)
        self.height = min(
            Window.height - self._bottom() - dp(Geometry.EDGE),
            dp(48 + 48 + 32)
            + self.column.minimum_height
            + self.actions.height
            + (self.footer.height + dp(16) if self.footer is not None else 0),
        )
        self._align_center()

    def _align_center(self, *_args: object) -> None:
        """Maps the native modal alignment hook to the approved compact/wide placement.

        Args:
            _args: Native modal/window geometry callback.
        Returns:
            None
        """
        self.center_x = Window.center[0]
        if Window.width >= dp(Geometry.BREAKPOINT):
            self.center_y = (Window.height - dp(Geometry.EDGE) + self._bottom()) / 2
        else:
            self.y = self._bottom()

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
        if ActionSheet.current is not None:
            ActionSheet.current.dismiss(animation=False)
        if not self.controller.state.covered:
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
        if ActionSheet.current is self:
            self.cancel.focus = True

    def _dismissed(self, *_args: object) -> None:
        """Releases old labels and the global modal reference immediately.

        Args:
            _args: Native dismissal event.
        Returns:
            None
        """
        Window.unbind(size=self._resize)
        if self.footer is not None:
            self.footer.unbind(height=self._resize)
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
        sheet._update_call_indicator()
        state = sheet.controller.state
        if state.covered or state.generation != sheet._generation:
            sheet.dismiss(animation=False)
        elif sheet._snapshot != id(state.snapshot) or (
            sheet._eligibility_revision is not None
            and sheet._eligibility_key != sheet._eligibility_revision()
        ):
            sheet._snapshot = id(state.snapshot)
            sheet._eligibility_key = (
                sheet._eligibility_revision() if sheet._eligibility_revision else None
            )
            if sheet.rebuild_on_snapshot:
                sheet._build()
                sheet.cancel.focus = True

    def _update_call_indicator(self) -> None:
        """Makes incoming activity reachable above the native modal without stealing focus.

        Args:
            None
        Returns:
            None
        """
        visible = any(
            item.phase != 'ended' for item in self.controller.calls.entries.values()
        )
        if visible and self.call_indicator.parent is None:
            self.header.add_widget(self.call_indicator, index=1)
        elif not visible and self.call_indicator.parent is not None:
            self.header.remove_widget(self.call_indicator)

    def _open_call(self) -> None:
        """Cancels this modal before the user's explicit switch to an incoming request.

        Args:
            None
        Returns:
            None
        """
        self.dismiss(animation=False)
        self.controller.calls.show()


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
        body.add_widget(Label(explanation, tone='textSecondary'))

    def accept() -> None:
        sheet.dismiss(animation=False)
        if not controller.state.covered:
            action()

    sheet = ActionSheet(controller, build, title=title, primary=(title, accept))
    sheet.show()
