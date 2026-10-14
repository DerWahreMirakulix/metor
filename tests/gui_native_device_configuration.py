"""Native simulator density, mounted geometry and touch-input acceptance."""

# ruff: noqa: E402

import argparse
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

os.environ['KIVY_NO_ARGS'] = '1'
os.environ['KIVY_NO_FILELOG'] = '1'
os.environ['KIVY_NO_CONFIG'] = '1'
os.environ['MESA_SHADER_CACHE_DISABLE'] = 'true'

from kivy.config import Config

Config.set('graphics', 'width', '720')
Config.set('graphics', 'height', '1328')

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp

from gui_native_render import capture_viewport
from metor.client import FrontendHost, FrontendLaunchContext
from metor.core.api import ContactEntry, Delivery, RuntimeSnapshotEvent
from metor.ui.gui.app import MetorApp
from metor.ui.gui.constants import Geometry
from metor.ui.gui.platform import read_configuration
from metor.ui.gui.state import Route
from metor.utils import open_private_binary_file


DEVICE = """schema_version = 1
[display]
adapter = 'simulator'
width_px = 1280
height_px = 720
rotation_deg = 90
scale = 2
[input]
adapter = 'simulator'
ptt_binding = 'ptt'
power_binding = 'power'
touch = true
[audio]
adapter = 'none'
"""
ACCEPTANCE_SECONDS = 15.0


def main() -> None:
    """Exercise parsed deployment geometry on a real SDL window and event loop."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'device.toml'
        with open_private_binary_file(path) as target:
            target.write(DEVICE.encode('utf-8'))
        configuration = read_configuration(str(path), simulator=True)
    assert configuration.logical_size == (360, 640)
    app = MetorApp(
        FrontendLaunchContext('Simulator', cast(FrontendHost, object())), configuration
    )
    with patch(
        'metor.ui.gui.app.Window',
        SimpleNamespace(system_size=(360, 664), width=720, height=1328),
    ):
        assert app._window_units(720, 1328) == (360, 664)
    with patch(
        'metor.ui.gui.app.Window',
        SimpleNamespace(system_size=(0, 0), width=0, height=0),
    ):
        assert app._window_units(720, 1328) == (360, 664)
    controller = app.controller
    controller.open_profile()
    controller.state.snapshot = RuntimeSnapshotEvent(
        'Simulator',
        '',
        epoch='simulator',
        profile_instance_id='device-configuration-fixture',
        contacts=[ContactEntry('Peer', 'peer')],
    )
    controller.state.route = Route('V08', 'peer', Delivery.DROP)
    completed = False

    def verify_window(_elapsed: float) -> None:
        """Require native pixels and logical controls to agree with the TOML."""
        assert tuple(Window.size) == (720, 1328), tuple(Window.size)
        assert dp(1) == configuration.scale
        assert Window.minimum_width == dp(Geometry.MIN_WIDTH)
        assert Window.minimum_height == dp(Geometry.MIN_HEIGHT + 24)
        assert app.shell is not None
        assert tuple(app.shell.size) == (720, 1280), tuple(app.shell.size)
        peer = app.shell._peer_panel
        assert peer is not None, (
            controller.state.route,
            controller.state.covered,
            [type(child).__name__ for child in app.shell.children],
        )
        assert peer.composer.entry.height >= dp(Geometry.TARGET)
        assert not controller.voice.routes.available
        assert not controller.voice.routes.scan()
        assert not controller.device.enabled
        assert controller.client is None
        peer.composer.entry.focus = True
        Clock.schedule_once(verify_keyboard, 0.5)

    def verify_keyboard(_elapsed: float) -> None:
        """Require declared touch input to dock a usable keyboard at scaled size."""
        nonlocal completed
        assert app.input_dock is not None and app.input_dock.keyboard is not None
        assert app.shell is not None and app.shell._peer_panel is not None
        entry = app.shell._peer_panel.composer.entry
        keyboard = app.input_dock.keyboard
        assert app.input_dock.target is entry
        assert keyboard.height == dp(Geometry.KEYBOARD)
        assert keyboard.width == Window.width
        assert entry.to_window(*entry.pos)[1] >= keyboard.top - 1
        assert app.root is not None
        args.output.parent.mkdir(parents=True, exist_ok=True)
        capture_viewport(app.root, args.output)
        app.input_dock.hide()
        entry.focus = False
        assert app.input_dock.keyboard is None
        assert controller.client is None
        completed = True
        deadline.cancel()
        print('NATIVE_GUI_DEVICE_CONFIGURATION_OK')
        app.stop()

    def timed_out(_elapsed: float) -> None:
        """Fail a live native loop that did not complete the bounded checks."""
        raise AssertionError('Native device configuration acceptance timed out')

    deadline = Clock.schedule_once(timed_out, ACCEPTANCE_SECONDS)
    Clock.schedule_once(verify_window, 0.8)
    with patch('metor.ui.gui.app.create_desktop_lifecycle_source', return_value=None):
        app.run()
    assert completed, 'Native device configuration acceptance did not complete'


if __name__ == '__main__':
    main()
