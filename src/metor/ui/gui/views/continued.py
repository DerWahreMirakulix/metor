"""Non-identifying media safety controls for the exact Core-authorized locked context."""

from collections.abc import Callable

from kivy.metrics import dp
from kivy.graphics import Color, Ellipse
from kivy.uix.floatlayout import FloatLayout

from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Label, Panel
from metor.ui.gui.widgets.ptt import PttAction
from metor.ui.gui.runtime.voice.press import PressPhase
from metor.ui.gui.platform.audio import PcmVoice
from metor.ui.gui.theme import color


class ContinuedOverlay(FloatLayout):
    """Preserves the native PTT widget while updating only permitted media feedback."""

    def __init__(
        self, controller: GuiController, refresh: Callable[[], None], **kwargs: object
    ) -> None:
        """Creates an initially hidden safety strip without acquiring input focus.

        Args:
            controller: Current public GUI controller.
            refresh: Native repaint request.
            kwargs: Native viewport arguments.
        Returns:
            None
        """
        super().__init__(**kwargs)
        self.controller = controller
        self.refresh = refresh
        self.panel: Panel | None = None
        self.ptt: PttAction | None = None
        self.label: Label | None = None
        self.keyboard_inset = 0.0
        self.safe_bottom = 0.0
        self.bind(size=lambda *_args: self.refresh())

    def render(self) -> None:
        """Paints no peer identity and keeps a visible cue through native media shutdown.

        Args:
            None
        Returns:
            None
        """
        controller, state = self.controller, self.controller.state
        continued, voice = controller.security.continuation, controller.voice
        visible = (
            state.covered
            and state.route.view == 'V05'
            and (
                continued.scope is not None
                or (
                    continued.requested is not None
                    and (voice.running or controller.playback.running)
                )
            )
        )
        if not visible:
            self.clear_widgets()
            self.panel = self.ptt = self.label = None
            self.safe_bottom = 0.0
            return
        if self.panel is None:
            self.panel = Panel(
                orientation='vertical',
                padding=dp(8),
                spacing=dp(8),
                size_hint=(None, None),
            )
            self.label = Label('Live active', role='support', tone='live')
            self.ptt = PttAction(controller, self.refresh)
            self.ptt.size_hint_x = 1
            self.panel.add_widget(self.label)
            self.panel.add_widget(self.ptt)
            self.add_widget(self.panel)
        assert (
            self.panel is not None and self.ptt is not None and self.label is not None
        )
        elapsed = PcmVoice.duration_ms(voice.accepted_bytes) // 1000
        self.label.text = (
            f'Recording · {elapsed // 60}:{elapsed % 60:02d}'
            if voice.press.phase is PressPhase.RECORDING
            else 'Finishing recording…'
            if voice.running and voice.press.phase is not PressPhase.STARTING
            else 'Starting recording…'
            if voice.press.phase is PressPhase.STARTING
            else 'Receiving audio'
            if controller.playback.running
            else 'Live active'
        )
        recording = voice.press.phase is PressPhase.RECORDING
        self.label.color = color('danger' if recording else 'live')
        self.label.padding = (dp(16) if recording else 0, 0)
        self.label.canvas.after.clear()
        if recording:
            with self.label.canvas.after:
                Color(*color('danger'))
                Ellipse(
                    pos=(self.label.x, self.label.center_y - dp(4)),
                    size=(dp(8), dp(8)),
                )
        self.ptt.label.text = (
            'Release to finish'
            if voice.press.active
            else 'Release to continue'
            if voice.press.held
            else 'Hold to talk'
        )
        self.ptt.disabled = not voice.available() and not voice.press.active
        self.panel.width = min(dp(480), self.width - dp(48))
        self.panel.height = self.label.height + dp(72)
        self.panel.x = self.x + (self.width - self.panel.width) / 2
        self.panel.y = self.y + max(dp(24), self.keyboard_inset + dp(8))
        self.safe_bottom = self.panel.top - self.y + dp(16)
