"""Native SDL/Kivy application lifecycle and generation-safe GUI polling."""

from kivy.app import App
from kivy.clock import Clock
from kivy.config import Config
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.input.motionevent import MotionEvent
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout

from metor.client import FrontendLaunchContext
from metor.ui.gui.constants import Geometry, GuiLimits
from metor.ui.gui.platform import DeviceConfiguration
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.runtime.voice import PressSource
from metor.ui.gui.theme import color
from metor.ui.gui.views import Shell
from metor.ui.gui.widgets import Label
from metor.ui.gui.widgets import TextField
from metor.ui.gui.widgets.sheet import ActionSheet
from metor.ui.gui.views.input import InputDock
from metor.ui.gui.views.calls import CallOverlay
from metor.ui.gui.views.continued import ContinuedOverlay
from metor.ui.gui.views.profiles import request_exit


class MetorApp(App):
    """One shared desktop/simulator GUI; no platform action implies host shutdown."""

    def __init__(
        self,
        context: FrontendLaunchContext,
        configuration: DeviceConfiguration,
        **kwargs: object,
    ) -> None:
        """Creates an app without starting a profile or probing capture devices.

        Args:
            context: Typed public launch context.
            configuration: Validated deployment mode.
            kwargs: Native application arguments.
        Returns:
            None
        """
        super().__init__(**kwargs)
        self.configuration = configuration
        self.controller = GuiController(context, configuration.mode == 'simulator')
        self.title = 'Metor · Simulator' if self.controller.simulator else 'Metor'
        self.exit_status: int = 0
        self.shell: Shell | None = None
        self.viewport: BoxLayout | None = None
        self.input_dock: InputDock | None = None
        self.call_overlay: CallOverlay | None = None
        self.continued_overlay: ContinuedOverlay | None = None
        self._prompt_identity: object = None
        self._render_trigger = Clock.create_trigger(self._render, 0)

    def build(self) -> BoxLayout:
        """Configures one native window and its responsive inner application viewport.

        Args:
            None
        Returns:
            BoxLayout: Native application root.
        """
        Config.set('kivy', 'exit_on_escape', '0')
        Window.clearcolor = color('background')
        width, height = self.configuration.logical_size
        Window.size = (dp(width), dp(height))
        Window.minimum_width = dp(Geometry.MIN_WIDTH)
        Window.minimum_height = dp(
            Geometry.MIN_HEIGHT + (24 if self.controller.simulator else 0)
        )
        root = BoxLayout(orientation='vertical')
        if self.controller.simulator:
            simulator_bar = BoxLayout(size_hint_y=None, height=dp(24))
            simulator_bar.add_widget(
                Label(
                    'SIMULATOR · no hardware or production profile actions',
                    role='support',
                    tone='live',
                    wrap=False,
                )
            )
            root.add_widget(simulator_bar)
            Window.size = (dp(width), dp(height) + dp(24))
        self.shell = Shell(self.controller, self.refresh)
        self.viewport = BoxLayout(orientation='vertical')
        self.viewport.add_widget(self.shell)
        stage = FloatLayout()
        stage.add_widget(self.viewport)
        self.continued_overlay = ContinuedOverlay(self.controller, self.refresh)
        stage.add_widget(self.continued_overlay)
        self.call_overlay = CallOverlay(self.controller, self.refresh)
        stage.add_widget(self.call_overlay)
        root.add_widget(stage)
        self.input_dock = InputDock(self, self.viewport)
        TextField.keyboard_owner = self.input_dock
        self.shell.bind(size=lambda *_args: self.refresh())
        Window.bind(on_request_close=self._close, on_keyboard=self._keyboard)
        Window.bind(
            on_key_down=self._key_down,
            on_key_up=self._key_up,
            on_touch_down=self._activity,
            on_touch_up=self._touch_up,
            focus=self._focus,
        )
        Clock.schedule_interval(self._poll, GuiLimits.UI_TICK_SECONDS)
        self.refresh()
        return root

    def refresh(self) -> None:
        """Coalesces redundant presentation updates into one native frame.

        Args:
            None
        Returns:
            None
        """
        self._render_trigger()

    def _render(self, _elapsed: float) -> None:
        """Paints only UI-thread state after layout updates settle.

        Args:
            _elapsed: Toolkit scheduling delta.
        Returns:
            None
        """
        ActionSheet.reconcile()
        if self.shell is not None:
            self.shell.render()
        if self.continued_overlay is not None:
            self.continued_overlay.keyboard_inset = (
                self.input_dock.keyboard.height
                if self.input_dock and self.input_dock.keyboard
                else 0
            )
            self.continued_overlay.render()
            if self.shell is not None:
                self.shell.inset_locked_media(self.continued_overlay.safe_bottom)
        if self.call_overlay is not None:
            self.call_overlay.bottom_inset = (
                self.continued_overlay.safe_bottom if self.continued_overlay else 0
            )
            self.call_overlay.render()

    def _poll(self, _elapsed: float) -> None:
        """Drains bounded SDK work while retaining responsive native input.

        Args:
            _elapsed: Toolkit scheduling delta.
        Returns:
            None
        """
        changed = self.controller.poll()
        if self.controller.lifecycle.exit_ready:
            self.stop()
            return
        if self.input_dock is not None:
            self.input_dock.poll()
        prompt = self.controller.interactions.prompt
        if prompt is not self._prompt_identity:
            self._prompt_identity = prompt
            changed = True
        if changed:
            self.refresh()

    def _activity(self, *_args: object) -> None:
        """Records deliberate native input for the application idle timer.

        Args:
            _args: Native input event fields.
        Returns:
            None
        """
        self.controller.security.activity()

    def _keyboard(self, _window: object, key: int, *_args: object) -> bool:
        """Provides safe Back without dismissing authorization covers.

        Args:
            _window: Native event source.
            key: Native key code.
            _args: Remaining event fields.
        Returns:
            bool: Whether the event was handled.
        """
        if (
            key == 27
            and self.input_dock is not None
            and self.input_dock.keyboard is not None
        ):
            self.input_dock.hide()
            return True
        if key == 27 and not self.controller.state.covered:
            self.controller.back()
            self.refresh()
            return True
        return False

    def _key_down(
        self,
        _window: object,
        key: int,
        _scan: int | None = None,
        _text: str | None = None,
        modifiers: list[str] | None = None,
    ) -> bool:
        """Observes key identity before widget dispatch and handles explicit Ctrl+Enter.

        Args:
            _window: Native window.
            key: Native key code.
            _scan: Native scancode.
            _text: Native text representation.
            modifiers: Current modifier names.
        Returns:
            bool: Whether an explicit send shortcut consumed the key.
        """
        self.controller.inputs.observe_key_down(str(key))
        self.controller.security.activity()
        route = self.controller.state.route
        if (
            key == 13
            and self.controller.inputs.fresh_key(str(key))
            and modifiers
            and 'ctrl' in modifiers
            and route.peer
            and route.view in {'V08', 'V09'}
            and not self.controller.state.covered
        ):
            self.controller.send_text(route.peer, route.delivery)
            self.refresh()
            return True
        return False

    def _key_up(self, _window: object, key: int, *_args: object) -> bool:
        """Releases the original PTT owner even after its widget/profile disappeared.

        Args:
            _window: Native window.
            key: Released native key code.
            _args: Remaining native key metadata.
        Returns:
            bool: False preserves ordinary keyboard dispatch.
        """
        if self.controller.inputs.observe_key_up(str(key)):
            self.refresh()
        return False

    def _touch_up(self, _window: object, touch: MotionEvent) -> bool:
        """Routes a captured pointer release independently of the current view tree.

        Args:
            _window: Native window.
            touch: Released pointer identity.
        Returns:
            bool: False permits native button feedback to finish.
        """
        if self.controller.inputs.up(PressSource.POINTER, str(touch.uid)):
            self.refresh()
        return False

    def _focus(self, _window: object, focused: bool) -> None:
        """Stops capture on application focus loss without synthesizing release.

        Args:
            _window: Native window.
            focused: Current foreground focus.
        Returns:
            None
        """
        self.controller.playback.auto.focused = focused
        if not focused:
            self.controller.inputs.focus_lost()
            self.controller.voice.depart()
            self.controller.playback.stop()
            self.refresh()

    def on_pause(self) -> bool:
        """Covers and safely stops capture on supported native suspend notifications.

        Args:
            None
        Returns:
            bool: True retains the application behind its authorization cover.
        """
        self.controller.voice.depart()
        self.controller.security.lock()
        return True

    def _close(self, *_args: object, **_kwargs: object) -> bool:
        """Keeps the window responsive until this GUI's local finalization and detach finish.

        Args:
            _args: Native window event.
            _kwargs: Native event metadata.
        Returns:
            bool: True intercepts native closure until local lifecycle handling completes.
        """
        request_exit(self.controller)
        self.refresh()
        return True

    def on_stop(self) -> None:
        """Cancels pending prompts and releases this GUI's client on exit.

        Args:
            None
        Returns:
            None
        """
        if self.input_dock is not None:
            self.input_dock.hide()
        TextField.keyboard_owner = None
        Window.unbind(
            on_request_close=self._close,
            on_keyboard=self._keyboard,
            on_key_down=self._key_down,
            on_key_up=self._key_up,
            on_touch_down=self._activity,
            on_touch_up=self._touch_up,
            focus=self._focus,
        )
        self.controller.close()
        ActionSheet.reconcile()
