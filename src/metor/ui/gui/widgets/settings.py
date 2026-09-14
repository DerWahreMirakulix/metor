"""Growing native settings rows with a shared title/support group and trailing value."""

from collections.abc import Callable

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
        self.remove_widget(self.label)
        self.padding = (dp(20), dp(16))
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
        trailing = Label(value, role='support', tone='textSecondary')
        trailing.size_hint_x = None
        trailing.width = max(dp(64), sp(64))
        trailing.halign = 'right'
        trailing.pos_hint = {'center_y': 0.5}
        self.add_widget(trailing)
        self.accessible_name = title + ': ' + value + '. ' + scope

        def measure(*_args: object) -> None:
            """Grows the whole row for measured wrapped title, help and value.

            Args:
                _args: Native font/layout changes.
            Returns:
                None
            """
            self.height = max(dp(76), group.height + dp(32), trailing.height + dp(32))

        group.bind(height=measure)
        trailing.bind(height=measure)
        measure()
