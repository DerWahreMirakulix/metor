"""Growing native settings rows with a shared title/support group and trailing value."""

from collections.abc import Callable

from kivy.core.text import Label as TextMeasure
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout

# Local Package Imports
from .controls import Action, Label


class SettingRow(Action):
    """Keeps scope and value readable without changing the authoritative setting locally."""

    def __init__(
        self,
        title: str,
        value: str,
        scope: str,
        callback: Callable[[], object],
        **kwargs: object,
    ) -> None:
        """Builds one measured 76-unit minimum settings target.

        Args:
            title: User-facing setting name.
            value: Current authoritative value or action label.
            scope: Plain meaning and scope.
            callback: Explicit edit action.
            kwargs: Native enabled/layout properties.
        Returns:
            None
        """
        super().__init__(title, callback, surface='surface', tone='text', **kwargs)
        self.focus_key = ('setting', title)
        self.remove_widget(self.label)
        horizontal_padding, vertical_padding = dp(20), dp(16)
        self.padding = (horizontal_padding, vertical_padding)
        self.spacing = dp(12)
        group = BoxLayout(
            orientation='vertical',
            spacing=dp(4),
            size_hint_y=None,
            pos_hint={'center_y': 0.5},
        )
        group.bind(minimum_height=group.setter('height'))
        group.add_widget(Label(title, role='row'))
        group.add_widget(Label(scope, role='support', tone='textSecondary'))
        self.add_widget(group)
        trailing = Label(value, role='support')
        trailing.pos_hint = {'center_y': 0.5}
        self.add_widget(trailing)
        self.accessible_name = title + ': ' + value + '. ' + scope
        natural_width = TextMeasure(
            font_name=trailing.font_name, font_size=trailing.font_size
        ).get_extents(value)[0] + dp(2)

        def measure(*_args: object) -> None:
            """Grows the whole row for measured wrapped title, help and value.

            Args:
                _args: Native font/layout changes.
            Returns:
                None
            """
            available = max(0, self.width - 2 * horizontal_padding)
            value_width = min(natural_width, available * 0.4)
            if available - value_width - dp(12) < sp(140):
                self.orientation = 'vertical'
                self.spacing = dp(6)
                trailing.size_hint_x = 1
                trailing.halign = 'left'
                content_height = group.height + self.spacing + trailing.height
            else:
                self.orientation = 'horizontal'
                self.spacing = dp(12)
                trailing.size_hint_x = None
                trailing.width = value_width
                trailing.halign = 'right'
                content_height = max(group.height, trailing.height)
            self.height = max(dp(76), content_height + 2 * vertical_padding)

        self.bind(width=measure)
        group.bind(height=measure)
        trailing.bind(height=measure)
        measure()
