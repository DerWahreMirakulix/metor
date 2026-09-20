"""Native packaged-font, pointer-tooltip and privacy-revocation checks without Core IO."""

# ruff: noqa: E402

import argparse
import os
from pathlib import Path
from typing import cast

os.environ['KIVY_NO_ARGS'] = '1'
if os.name == 'nt':
    os.environ['KCFG_GRAPHICS_WINDOW_STATE'] = 'hidden'
os.environ['KIVY_NO_FILELOG'] = '1'
os.environ['KIVY_NO_CONFIG'] = '1'
os.environ['MESA_SHADER_CACHE_DISABLE'] = 'true'

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import Metrics

from metor.client import FrontendHost, FrontendLaunchContext
from metor.core.api import (
    ContactEntry,
    DropConversationSummaryEntry,
    RuntimeSnapshotEvent,
)
from metor.ui.gui.app import MetorApp
from metor.ui.gui.platform import DeviceConfiguration
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import Label, SecretInput, TextField
from metor.ui.gui.widgets.symbol import IconAction


def main() -> None:
    """Checks real native text textures and cancels a pending/visible hint on cover.

    Args:
        None
    Returns:
        None
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    Metrics.fontscale = 1.5
    app = MetorApp(
        FrontendLaunchContext('Simulator', cast(FrontendHost, object())),
        DeviceConfiguration(mode='simulator', width_px=360, height_px=640),
    )
    controller = app.controller
    controller.open_profile()
    alias = 'שלום · العربية · 漢字'
    controller.state.snapshot = RuntimeSnapshotEvent(
        profile='Simulator',
        onion='',
        epoch='simulator',
        contacts=[ContactEntry(alias, 'unicode-peer')],
        conversations=[DropConversationSummaryEntry(alias, 'unicode-peer', 1)],
    )
    controller.state.covered = False
    controller.state.route = Route('V06')

    def inspect(_elapsed: float) -> None:
        """Validates real widgets before capturing the visible pointer hint.

        Args:
            _elapsed: Native layout settlement delay.
        Returns:
            None
        """
        assert app.shell is not None and app.viewport is not None
        labels = [widget for widget in app.shell.walk() if isinstance(widget, Label)]
        name = next(widget for widget in labels if widget.text == alias)
        assert Path(name.font_name).name == 'DejaVuSans-Bold.ttf'
        assert name.texture is not None and name.texture.width > 0
        field = TextField(text=alias)
        assert field.text == alias
        assert Path(field.font_name).name == 'DejaVuSans.ttf'
        secret = SecretInput(text=alias)
        assert secret.text == alias and secret.password
        assert Path(secret.font_name).name == 'InterTight-400.ttf'
        icon = next(
            widget
            for widget in app.shell.walk()
            if isinstance(widget, IconAction)
            and widget.accessible_name.startswith('Notifications')
        )
        icon._pointer(Window, icon.to_window(*icon.center))
        assert icon._hovered
        icon.tooltip.cancel()
        icon.tooltip._show(0)
        assert icon.tooltip.visible and icon.tooltip.label is not None
        assert icon.tooltip.label.text == icon.accessible_name
        assert not icon.focus and controller.state.route.view == 'V06'

        def capture_and_cover(_delta: float) -> None:
            """Captures after native text layout and then verifies synchronous revocation.

            Args:
                _delta: One native frame delay.
            Returns:
                None
            """
            assert app.root is not None and app.shell is not None
            assert icon.tooltip.visible
            args.output.parent.mkdir(parents=True, exist_ok=True)
            app.root.export_to_png(str(args.output))
            controller.state.covered = True
            controller.state.snapshot = None
            controller.state.route = Route('V05')
            app.shell.render()
            assert not icon.tooltip.visible and icon.tooltip.label is None
            assert all(
                getattr(widget, 'text', '') != alias for widget in app.shell.walk()
            )
            assert controller.client is None
            print('NATIVE_GUI_FALLBACK_TOOLTIP_PRIVACY_OK')
            app.stop()

        Clock.schedule_once(capture_and_cover, 0)

    Clock.schedule_once(inspect, 1.0)
    app.run()


if __name__ == '__main__':
    main()
