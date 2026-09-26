"""Native field focus and software-keyboard docking without a persistent input history."""

from typing import TYPE_CHECKING

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView

from metor.ui.gui.constants import Geometry
from metor.ui.gui.widgets import TextField
from metor.ui.gui.widgets.keyboard import LocalKeyboard
from metor.ui.gui.widgets.sheet import ActionSheet

if TYPE_CHECKING:
    from metor.ui.gui.app import MetorApp


class InputDock:
    """Keeps one currently focused field above a local keyboard in the native app root."""

    def __init__(self, app: 'MetorApp', root: BoxLayout) -> None:
        """Installs an inert dock owner without inspecting or copying any field content.

        Args:
            app: Current native application.
            root: Vertical owner of the shell and keyboard inset.
        Returns:
            None
        """
        self.app, self.root = app, root
        self.target: TextField | None = None
        self.keyboard: LocalKeyboard | None = None
        self._context: tuple[int, str, str | None] | None = None
        self._dismissed: int | None = None
        self._sheet: ActionSheet | None = None

    def focused(self, field: TextField) -> None:
        """Automatically opens only when touch input is declared.

        Args:
            field: Newly focused local text/password/PIN field.
        Returns:
            None
        """
        if self.target is field or self._dismissed == id(field):
            return
        if self.app.configuration.touch:
            self.show(field)

    def unfocused(self, field: TextField) -> None:
        """Clears an explicit Hide once the field loses native focus.

        Args:
            field: Field that left the current focus path.
        Returns:
            None
        """
        if self.target is field:
            self.hide()
        if self._dismissed == id(field):
            self._dismissed = None

    def show(self, field: TextField) -> None:
        """Shows an explicitly requested keyboard while keeping the current field focused.

        Args:
            field: Exact current field; content is never copied into the dock.
        Returns:
            None
        """
        state, voice = self.app.controller.state, self.app.controller.voice
        if (
            field.disabled
            or field.readonly
            or field.get_root_window() is None
            or voice.press.active
        ):
            return
        if state.route.peer in voice.reviews and state.route.view == 'V08':
            return
        sheet = ActionSheet.current
        if sheet is not None and not any(widget is field for widget in sheet.walk()):
            return
        if self.keyboard is not None and sheet is not self._sheet:
            self.hide()
        self._sheet = sheet
        if self.target is not None:
            self.target.local_keyboard_visible = False
        self.target = field
        field.local_keyboard_visible = True
        self._dismissed = None
        field.focus = True
        self._context = state.generation, state.route.view, state.route.peer
        preferences = state.preferences
        layout = preferences.preferences.keyboard_layout if preferences else 'qwerty'
        if self.keyboard is None:
            self.keyboard = LocalKeyboard(
                self._edit, self.hide, layout=layout, pin=field.input_purpose == 'pin'
            )
            if sheet is None:
                if self.app.shell is not None:
                    self.app.shell.set_input_inset(dp(Geometry.KEYBOARD))
                self.root.add_widget(self.keyboard)
            else:
                # Native Window placement keeps local keys above the modal's veil.
                # The exact modal target is revalidated before each edit.
                self.keyboard.size_hint = (None, None)
                Window.add_widget(self.keyboard)
                Window.bind(size=self._place_modal_keyboard)
                self._place_modal_keyboard()
        else:
            self.keyboard.configure(layout=layout, pin=field.input_purpose == 'pin')
        Clock.schedule_once(self._reveal, 0)
        self.app.refresh()

    def _edit(self, value: str) -> None:
        """Routes one explicit key directly into the current native input field.

        Args:
            value: Printable local character or fixed Backspace/Enter operation.
        Returns:
            None
        """
        field = self.target
        if (
            field is None
            or field.disabled
            or field.readonly
            or field.get_root_window() is None
            or (self._sheet is not None and self._sheet is not ActionSheet.current)
        ):
            self.hide()
            return
        self.app.controller.security.activity()
        if value == 'backspace':
            field.do_backspace()
        elif value == 'enter':
            if field.multiline:
                field.insert_text('\n')
            else:
                field.dispatch('on_text_validate')
        else:
            field.insert_text(value)
        Clock.schedule_once(self._reveal, 0)

    def _place_modal_keyboard(self, *_args: object) -> None:
        """Places full-width local keys above the viewport's native bottom inset.

        Args:
            _args: Native window geometry callbacks.
        Returns:
            None
        """
        if self.keyboard is not None and self._sheet is not None:
            self.keyboard.width = Window.width
            self.keyboard.pos = (0, self.root.y)
            self._sheet.set_keyboard_top(self.keyboard.top)

    def _reveal(self, _elapsed: float) -> None:
        """Scrolls a form's actual focused field into the remaining visible area.

        Args:
            _elapsed: Native layout scheduler interval.
        Returns:
            None
        """
        field = self.target
        parent = field.parent if field is not None else None
        while parent is not None and parent.parent is not parent:
            if isinstance(parent, ScrollView):
                parent.scroll_to(field, padding=dp(Geometry.EDGE), animate=False)
                break
            parent = parent.parent

    def hide(self) -> None:
        """Releases the field reference and preserves explicit keyboard dismissal.

        Args:
            None
        Returns:
            None
        """
        if self.target is not None:
            self._dismissed = id(self.target)
            self.target.local_keyboard_visible = False
        self.target = None
        if self.keyboard is not None:
            parent = self.keyboard.parent
            if parent is not None:
                parent.remove_widget(self.keyboard)
            self.keyboard = None
        Window.unbind(size=self._place_modal_keyboard)
        if self._sheet is not None:
            self._sheet.set_keyboard_top(0)
            self._sheet = None
        if self.app.shell is not None:
            self.app.shell.set_input_inset(0)
        self._context = None
        self.app.refresh()

    def poll(self) -> None:
        """Revokes the dock on field/view departure, capture or owned Voice review.

        Args:
            None
        Returns:
            None
        """
        if self.keyboard is None:
            return
        state, voice = self.app.controller.state, self.app.controller.voice
        field = self.target
        if (
            field is None
            or not field.focus
            or field.get_root_window() is None
            or self._sheet is not None
            and self._sheet is not ActionSheet.current
            or self._context != (state.generation, state.route.view, state.route.peer)
            or voice.press.active
            or state.route.view == 'V08'
            and state.route.peer in voice.reviews
        ):
            self.hide()
