"""Closed audio configuration and deliberate recovery dialogs without media activation."""

from collections.abc import Callable
from functools import partial
from typing import Literal

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from metor.ui.gui.runtime import GuiController
from metor.ui.gui.runtime.voice import group_endpoints
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
        purpose: User action requiring explicitly selected audio endpoints.
    Returns:
        None. No endpoint is probed and no capture, playback or call is started.
    """
    if controller.state.covered:
        return
    title, explanation = {
        'recording': (
            'Recording unavailable',
            'Choose a microphone in audio settings before recording a voice message.',
        ),
        'playback': (
            'Playback unavailable',
            'Choose an audio output in audio settings before playing a voice message.',
        ),
        'calls': (
            'Calls unavailable',
            'Choose a microphone and audio output in audio settings before starting or accepting a call.',
        ),
    }[purpose]
    progress = controller.playback.progress
    if (
        purpose == 'playback'
        and progress is not None
        and progress.state == 'output_unavailable'
    ):
        explanation = 'The selected output could not play audio. Choose a different output in audio settings.'

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

    sheet = ActionSheet(
        controller,
        lambda body: body.add_widget(audio_routes_body(controller, refresh)),
        title='Audio settings',
        stable_frame=True,
        revision=partial(_revision, controller),
        snapshot_updates=False,
        wrap_title=True,
    )
    sheet.show()
    if not controller.voice.routes.scanned:
        controller.voice.routes.scan()
    refresh()


def _choose_endpoint(
    controller: GuiController,
    refresh: Callable[[], None],
    *,
    microphone: bool,
    advanced: bool = False,
) -> None:
    """Opens a bounded keyboard-accessible device list inside its own closed modal."""
    if controller.state.covered:
        return
    routes = controller.voice.routes

    def build(body: BoxLayout) -> None:
        """Projects current endpoints without keeping a stale device permission."""
        selected = routes.input if microphone else routes.output
        groups = group_endpoints(
            routes.endpoints, microphone=microphone, selected=selected
        )
        for group in groups:
            for item in group.variants if advanced else (group.preferred,):
                error = item.input_error if microphone else item.output_error
                action = Action(
                    item.name if advanced else group.name,
                    partial(select, item.index),
                    surface='liveSurface' if item.index == selected else 'raised',
                    disabled=bool(error) or routes.blocked,
                )
                body.add_widget(action)
                if error:
                    body.add_widget(Label(error, role='caption', tone='textSecondary'))
        if not advanced and any(len(group.variants) > 1 for group in groups):
            body.add_widget(
                Action(
                    'Other device variants',
                    partial(
                        _choose_endpoint,
                        controller,
                        refresh,
                        microphone=microphone,
                        advanced=True,
                    ),
                )
            )

    def select(endpoint: int) -> None:
        """Stores an explicit currently enumerated choice, then returns to settings."""
        if not routes.select(endpoint, microphone=microphone):
            refresh()
            return
        show_audio_routes(controller, refresh)

    sheet = ActionSheet(
        controller,
        build,
        title=('Microphone variants' if microphone else 'Audio output variants')
        if advanced
        else ('Choose microphone' if microphone else 'Choose audio output'),
        stable_frame=True,
        revision=partial(_revision, controller),
        snapshot_updates=False,
        wrap_title=True,
        back=partial(_choose_endpoint, controller, refresh, microphone=microphone)
        if advanced
        else partial(show_audio_routes, controller, refresh),
    )
    sheet.show()
    refresh()


def audio_routes_body(
    controller: GuiController,
    refresh: Callable[[], None],
) -> BoxLayout:
    """Builds the bounded contents of audio settings with explicit inert choices.

    Args:
        controller: Current GUI local audio configuration owner.
        refresh: Native repaint request for scans and selection.
    Returns:
        BoxLayout: Measured content intended only for a closed settings modal.
    """
    routes = controller.voice.routes
    blocked = routes.blocked
    body = BoxLayout(orientation='vertical', spacing=dp(12), size_hint_y=None)
    body.bind(minimum_height=body.setter('height'))
    body.add_widget(
        Label(
            'Changes apply immediately. Speakers may cause echo during calls; headphones can help.',
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
        (False, 'Audio output', routes.output),
    ):
        endpoints = [
            item
            for item in routes.endpoints
            if (item.input_available if microphone else item.output_available)
        ]
        body.add_widget(Label(heading, role='support'))
        name = next(
            (
                item.device_name or item.name
                for item in endpoints
                if item.index == selected
            ),
            None,
        )
        body.add_widget(
            Label(name or 'Not selected', role='caption', tone='textSecondary')
        )
        body.add_widget(
            Action(
                'Choose microphone' if microphone else 'Choose audio output',
                partial(_choose_endpoint, controller, refresh, microphone=microphone),
                disabled=blocked or not endpoints,
            )
        )
    if routes.scanned and not routes.endpoints:
        body.add_widget(
            Label(
                'No audio devices found. Connect a device and refresh.', role='support'
            )
        )

    return body
