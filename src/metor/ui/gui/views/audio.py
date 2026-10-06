"""Closed audio configuration and deliberate recovery dialogs without media activation."""

from collections.abc import Callable
from functools import partial
from typing import Literal

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Action, Label
from metor.ui.gui.widgets.sheet import ActionSheet


AudioPurpose = Literal['recording', 'playback', 'calls']


def show_audio_unavailable(
    controller: GuiController,
    refresh: Callable[[], None],
    *,
    purpose: AudioPurpose = 'calls',
) -> None:
    """Explains missing media setup before an explicit switch to audio settings.

    Args:
        controller: Current presentation and local audio route owner.
        refresh: Native presentation refresh.
        purpose: User action requiring a confirmed headset route.
    Returns:
        None. No endpoint is probed and no capture, playback or call is started.
    """
    if controller.state.covered:
        return
    title, explanation = {
        'recording': (
            'Recording unavailable',
            'Choose a microphone and headphone output in audio settings before recording a voice message.',
        ),
        'playback': (
            'Playback unavailable',
            'Choose a headphone output in audio settings before playing a voice message.',
        ),
        'calls': (
            'Calls unavailable',
            'Choose a microphone and headphone output in audio settings before starting or accepting a call.',
        ),
    }[purpose]

    def settings() -> None:
        """Moves from explanation to the closed settings modal without retrying media."""
        show_audio_routes(controller, refresh)

    sheet = ActionSheet(
        controller,
        lambda body: body.add_widget(Label(explanation, role='support')),
        title=title,
        primary=('Go to audio settings', settings),
        primary_tone='text',
        rebuild_on_snapshot=False,
        snapshot_updates=False,
        wrap_title=True,
    )
    sheet.show()
    refresh()


def _revision(controller: GuiController) -> tuple[object, ...]:
    """Tracks local route eligibility independently of unrelated Core snapshots."""
    voice = controller.voice
    return (
        controller.state.busy,
        voice.routes.scanned,
        voice.routes.endpoints,
        voice.routes.input,
        voice.routes.output,
        voice.headset_confirmed,
        voice.running,
        controller.playback.running,
        controller.calls.active,
        controller.calls.media_active,
    )


def show_audio_routes(controller: GuiController, refresh: Callable[[], None]) -> None:
    """Opens closed local audio settings without starting or retrying any media.

    Args:
        controller: Authorized route and device owner.
        refresh: Native presentation refresh.
    Returns:
        None. A first explicit settings visit may enumerate inert endpoints.
    """
    if controller.state.covered:
        return

    def changed() -> None:
        """Closes settings after explicit confirmation without resuming media."""
        sheet.dismiss(animation=False)
        refresh()

    sheet = ActionSheet(
        controller,
        lambda body: body.add_widget(audio_routes_body(controller, changed, refresh)),
        title='Audio settings',
        revision=partial(_revision, controller),
        snapshot_updates=False,
        wrap_title=True,
    )
    sheet.show()
    if not controller.voice.routes.scanned:
        controller.voice.routes.scan()
    refresh()


def _choose_endpoint(
    controller: GuiController, refresh: Callable[[], None], *, microphone: bool
) -> None:
    """Opens a bounded keyboard-accessible device list inside its own closed modal."""
    if controller.state.covered:
        return
    routes = controller.voice.routes

    def build(body: BoxLayout) -> None:
        """Projects current endpoints without keeping a stale device permission."""
        choices = [
            item
            for item in routes.endpoints
            if (item.input_available if microphone else item.output_available)
        ]
        for item in choices:
            selected = routes.input if microphone else routes.output
            action = Action(
                item.name,
                partial(select, item.index),
                surface='liveSurface' if item.index == selected else 'raised',
            )
            action.label.text_size = (None, None)
            action.label.shorten = True
            action.label.shorten_from = 'right'
            action.bind(
                width=lambda widget, width: setattr(
                    widget.label, 'text_size', (width - dp(24), None)
                )
            )
            body.add_widget(action)

    def select(endpoint: int) -> None:
        """Stores an explicit currently enumerated choice, then returns to settings."""
        valid = any(
            item.index == endpoint
            and (item.input_available if microphone else item.output_available)
            for item in routes.endpoints
        )
        if not valid:
            return
        if microphone:
            routes.input = endpoint
        else:
            routes.output = endpoint
        show_audio_routes(controller, refresh)

    sheet = ActionSheet(
        controller,
        build,
        title='Choose microphone' if microphone else 'Choose headphone output',
        revision=partial(_revision, controller),
        snapshot_updates=False,
        wrap_title=True,
    )
    sheet.show()
    refresh()


def audio_routes_body(
    controller: GuiController,
    confirmed: Callable[[], None],
    refresh: Callable[[], None],
) -> BoxLayout:
    """Builds the bounded contents of audio settings with explicit inert choices.

    Args:
        controller: Current GUI local audio configuration owner.
        confirmed: Closes the modal only after confirmed route installation.
        refresh: Native repaint request for scans and selection.
    Returns:
        BoxLayout: Measured content intended only for a closed settings modal.
    """
    voice, routes = controller.voice, controller.voice.routes
    blocked = bool(
        voice.running
        or controller.playback.running
        or controller.calls.active
        or controller.calls.media_active
    )
    body = BoxLayout(orientation='vertical', spacing=dp(12), size_hint_y=None)
    body.bind(minimum_height=body.setter('height'))
    body.add_widget(
        Label(
            'Use a headset. Speaker echo cancellation is unavailable.',
            role='support',
            tone='textSecondary',
        )
    )
    if blocked:
        body.add_widget(
            Label('Stop audio or end the call before changing devices.', role='support')
        )

    def scan() -> None:
        """Requests endpoint enumeration only after this explicit user action."""
        routes.scan()
        refresh()

    body.add_widget(
        Action(
            'Refresh audio devices' if routes.scanned else 'Find audio devices',
            scan,
            disabled=blocked or controller.state.busy or controller.simulator,
        )
    )
    for microphone, heading, selected in (
        (True, 'Microphone', routes.input),
        (False, 'Headphone output', routes.output),
    ):
        endpoints = [
            item
            for item in routes.endpoints
            if (item.input_available if microphone else item.output_available)
        ]
        body.add_widget(Label(heading, role='support'))
        name = next((item.name for item in endpoints if item.index == selected), None)
        body.add_widget(
            Label(name or 'Not selected', role='caption', tone='textSecondary')
        )
        body.add_widget(
            Action(
                'Choose microphone' if microphone else 'Choose headphone output',
                partial(_choose_endpoint, controller, refresh, microphone=microphone),
                disabled=blocked or not endpoints,
            )
        )
    if routes.scanned and not routes.endpoints:
        body.add_widget(
            Label(
                'No audio devices found. Connect a headset and refresh.', role='support'
            )
        )

    def confirm() -> None:
        """Installs the explicit route while leaving every media stream stopped."""
        if routes.confirm():
            confirmed()
        else:
            refresh()

    selected_input = any(
        item.index == routes.input and item.input_available for item in routes.endpoints
    )
    selected_output = any(
        item.index == routes.output and item.output_available
        for item in routes.endpoints
    )
    body.add_widget(
        Action(
            'Use this headset',
            confirm,
            disabled=blocked
            or controller.state.busy
            or not selected_input
            or not selected_output,
        )
    )
    return body
