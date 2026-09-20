"""Exercises the installed common CLI and GUI entry with an isolated data root.

Run outside the checkout with the installed interpreter and SDL display selected.
The timer closes the real application; it does not replace its event loop.
"""

# ruff: noqa: E402

import os
from pathlib import Path
import sys
import tempfile
import time

os.environ['KIVY_NO_ARGS'] = '1'
if os.name == 'nt':
    os.environ['KCFG_GRAPHICS_WINDOW_STATE'] = 'hidden'
os.environ['KIVY_NO_FILELOG'] = '1'
os.environ['KIVY_NO_CONSOLELOG'] = '1'
os.environ['KIVY_NO_CONFIG'] = '1'
os.environ['MESA_SHADER_CACHE_DISABLE'] = 'true'

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp

from metor.cli import run_cli
from metor.ui.gui.app import MetorApp


def main() -> None:
    """Runs the real discovered GUI with no profile activation or terminal prompt.

    Args:
        None
    Returns:
        None
    """
    simulator = '--simulator' in sys.argv[1:]
    observed: list[str] = []
    with tempfile.TemporaryDirectory(prefix='metor-gui-launch-') as directory:
        os.environ['METOR_DATA_DIR_PARENT'] = directory
        os.environ.pop('METOR_DEVICE_CONFIG', None)
        started = time.monotonic()

        def stop(_elapsed: float) -> None:
            """Verifies native startup before normal application shutdown.

            Args:
                _elapsed: Native scheduler interval.
            Returns:
                None
            """
            app = App.get_running_app()
            assert isinstance(app, MetorApp)
            expected = tuple(dp(value) for value in app.configuration.logical_size)
            if app.shell is None or tuple(app.shell.size) != expected:
                if time.monotonic() - started > 30:
                    raise AssertionError('Native launcher viewport did not settle')
                Clock.schedule_once(stop, 0.1)
                return
            assert app.controller.client is None
            assert app.controller.state.covered
            assert app.configuration.source is None
            assert app.configuration.mode == ('simulator' if simulator else 'desktop')
            observed.append(app.configuration.mode)
            app.stop()

        Clock.schedule_once(stop, 1)
        arguments = ['chat', '--ui', 'gui'] + (['--simulator'] if simulator else [])
        assert run_cli(arguments) == 0
        assert observed == [('simulator' if simulator else 'desktop')]
        assert not tuple(Path(directory).rglob('device.toml'))
        print('INSTALLED_GUI_REAL_LAUNCH_OK', observed[0])


if __name__ == '__main__':
    main()
