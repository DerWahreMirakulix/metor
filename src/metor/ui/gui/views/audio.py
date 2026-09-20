"""Explicit native headset routing controls with no automatic microphone activation."""

from collections.abc import Callable

from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.spinner import Spinner, SpinnerOption

from metor.ui.gui.runtime import GuiController
from metor.ui.gui.theme import color, font_path
from metor.ui.gui.widgets import Action, Label


class EndpointOption(SpinnerOption):
    """A measured native route choice with the same readable 48-unit target."""

    def __init__(self, **kwargs: object) -> None:
        """Applies local fonts and palette without interpreting device names as markup.

        Args:
            kwargs: Native dropdown properties.
        Returns:
            None
        """
        kwargs.update(
            height=dp(48),
            font_name=font_path(),
            font_size=sp(14),
            color=color('text'),
            background_normal='',
            background_color=color('raised'),
            markup=False,
        )
        super().__init__(**kwargs)
        self.bind(text=self._font_coverage)
        self._font_coverage()

    def _font_coverage(self, *_args: object) -> None:
        """Uses the packaged fallback for native endpoint names when needed.

        Args:
            _args: Native label change.
        Returns:
            None
        """
        self.font_name = font_path(text=self.text)


def audio_routes_body(
    controller: GuiController, refresh: Callable[[], None]
) -> BoxLayout:
    """Builds explicit input/output selection and headset-route confirmation.

    Args:
        controller: Current GUI service coordinator.
        refresh: Coalesced native repaint request.
    Returns:
        BoxLayout: Measured native headset settings.
    """
    routes = controller.voice.routes
    body = BoxLayout(orientation='vertical', spacing=dp(12), size_hint_y=None)
    body.bind(minimum_height=body.setter('height'))
    body.add_widget(Label('Headset', role='peer'))
    body.add_widget(
        Label(
            'Use headphones for simultaneous speaking and playback. Speaker echo cancellation is unavailable.',
            role='support',
            tone='textSecondary',
        )
    )

    def scan() -> None:
        """Requests deferred native enumeration after explicit user intent.

        Args:
            None
        Returns:
            None
        """
        routes.scan()
        refresh()

    body.add_widget(
        Action(
            'Refresh audio devices' if routes.scanned else 'Choose audio devices',
            scan,
            disabled=controller.state.busy
            or controller.voice.running
            or controller.simulator,
        )
    )
    if not routes.scanned:
        return body
    for is_input, label, selected in (
        (True, 'Microphone', routes.input),
        (False, 'Headphone output', routes.output),
    ):
        endpoints = [
            item
            for item in routes.endpoints
            if (item.input_available if is_input else item.output_available)
        ]
        choices: dict[str, int] = {}
        for item in endpoints:
            name = item.name
            if name in choices:
                name = f'{name} · {item.index}'
            choices[name] = item.index
        current = next(
            (name for name, index in choices.items() if index == selected),
            'Choose ' + label.lower(),
        )
        body.add_widget(Label(label, role='support'))
        selector = Spinner(
            text=current,
            values=tuple(choices),
            option_cls=EndpointOption,
            size_hint_y=None,
            height=dp(48),
            font_name=font_path(text=current),
            font_size=sp(14),
            color=color('text'),
            background_normal='',
            background_color=color('raised'),
            markup=False,
            disabled=not choices or controller.voice.running,
        )

        def choose(
            _widget: object,
            value: str,
            *,
            inputs: bool = is_input,
            mapping: dict[str, int] = choices,
        ) -> None:
            """Stores only the explicit endpoint choice in this GUI activation.

            Args:
                _widget: Native dropdown source.
                value: User-selected display label.
                inputs: Whether this is the microphone selector.
                mapping: Stable descriptor IDs from this scan.
            Returns:
                None
            """
            if value in mapping:
                if isinstance(_widget, Spinner):
                    _widget.font_name = font_path(text=value)
                if inputs:
                    routes.input = mapping[value]
                else:
                    routes.output = mapping[value]

        selector.bind(text=choose)
        body.add_widget(selector)

    def confirm() -> None:
        """Confirms headset routing without starting either native stream.

        Args:
            None
        Returns:
            None
        """
        routes.confirm()
        refresh()

    body.add_widget(
        Action(
            'Use this headset',
            confirm,
            disabled=controller.voice.running or controller.state.busy,
        )
    )
    if controller.voice.headset_confirmed:
        body.add_widget(
            Label('Headset selected for this session', role='support', tone='success')
        )
    return body
