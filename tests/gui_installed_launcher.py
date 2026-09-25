"""Exercise the wheel-installed CLI and native GUI through deliberate close."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch


_APP_READY_SECONDS = 30.0
_WORKER_SECONDS = 60.0
_POLL_SECONDS = 0.1
_CALLBACK_SECRET = 'synthetic-callback-secret'


def _worker(case: str) -> None:
    """Run one isolated actual toolkit event loop after its data root is fixed.

    Args:
        case: Empty catalog, missing requested profile, or callback failure.
    Returns:
        None
    """
    data_parent = Path(os.environ.get('METOR_DATA_DIR_PARENT', ''))
    if (
        not data_parent.is_absolute()
        or data_parent.name != case
        or not (data_parent / '.gui-smoke-owner').is_file()
    ):
        raise RuntimeError(
            'Installed GUI smoke requires its fresh temporary data root.'
        )
    from metor.application import initialize_runtime_environment
    from metor.cli.entry import run_cli
    from metor.data import ProfileManager
    from metor.ui.gui.platform import lifecycle as native_lifecycle

    installed_root = Path(sys.prefix).resolve()
    cli_source = Path(sys.modules[run_cli.__module__].__file__).resolve()
    assert cli_source.is_relative_to(installed_root), cli_source
    if case == 'picker':
        initialize_runtime_environment()
        ProfileManager('available').initialize()

    observed: list[str] = []
    observed_app: object | None = None
    started = time.monotonic()

    def observe(_elapsed: float) -> None:
        """Inspect the usable first view, then invoke the application's close path.

        Args:
            _elapsed: Native scheduler interval.
        Returns:
            None
        """
        nonlocal observed_app
        from kivy.app import App
        from kivy.clock import Clock
        from kivy.metrics import dp

        from metor.ui.gui.app import MetorApp
        from metor.ui.gui.widgets import Action, Label, SecretInput, TextField

        gui_source = Path(sys.modules[MetorApp.__module__].__file__).resolve()
        assert gui_source.is_relative_to(installed_root), gui_source
        app = App.get_running_app()
        if not isinstance(app, MetorApp) or app.shell is None:
            if time.monotonic() - started >= _APP_READY_SECONDS:
                raise AssertionError('Installed GUI did not build a window')
            Clock.schedule_once(observe, _POLL_SECONDS)
            return
        expected_size = tuple(dp(value) for value in app.configuration.logical_size)
        ready = (
            app.shell.get_root_window() is not None
            and tuple(app.shell.size) == expected_size
            and not app.controller.state.busy
        )
        if case == 'picker':
            page = app.controller.profiles.page
            ready = ready and page is not None and bool(page.entries)
        labels = {
            widget.text for widget in app.shell.walk() if isinstance(widget, Label)
        }
        actions = {
            widget.accessible_name: widget
            for widget in app.shell.walk()
            if isinstance(widget, Action)
        }
        if case == 'picker':
            ready = (
                ready
                and 'Choose profile' in labels
                and any(name.startswith('available') for name in actions)
            )
        else:
            ready = ready and 'New profile' in labels and 'Create profile' in actions
        if not ready:
            if time.monotonic() - started >= _APP_READY_SECONDS:
                raise AssertionError('Installed GUI first view did not settle')
            Clock.schedule_once(observe, _POLL_SECONDS)
            return

        assert app.configuration.mode == 'desktop'
        assert app.configuration.source is None
        assert app.controller.client is None
        assert app.controller.interactions.prompt is None
        assert app.controller.state.covered
        if case == 'picker':
            assert app.controller.state.route.view == 'V02'
            assert 'Choose profile' in labels
            assert any(name.startswith('available') for name in actions)
            assert not actions['New profile'].disabled
        else:
            assert app.controller.state.route.view == 'V03'
            assert 'New profile' in labels
            assert 'Create profile' in actions
            assert not actions['Create profile'].disabled
            assert any(isinstance(widget, TextField) for widget in app.shell.walk())
            assert (
                sum(isinstance(widget, SecretInput) for widget in app.shell.walk()) == 2
            )
        observed.append(case)
        observed_app = app
        if case == 'callback':
            raise RuntimeError(_CALLBACK_SECRET)
        assert app._close()

    arming_done = threading.Event()

    def arm_observer() -> None:
        """Register one observer only after the CLI imports the native toolkit.

        Args:
            None
        Returns:
            None
        """
        while not arming_done.wait(_POLL_SECONDS):
            gui_module = sys.modules.get('metor.ui.gui.app')
            if gui_module is not None and getattr(gui_module, 'MetorApp', None):
                from kivy.clock import Clock

                Clock.schedule_once(observe, 0)
                return

    observer_thread = threading.Thread(target=arm_observer, name='gui-smoke-observer')
    observer_thread.start()
    arguments = ['chat', '--ui', 'gui']
    if case == 'picker':
        arguments.extend(('-p', 'missing'))
    try:
        # The host OS lifecycle bus is outside this display and Close software gate.
        with patch.object(
            native_lifecycle, 'create_desktop_lifecycle_source', return_value=None
        ) as lifecycle_port:
            status = run_cli(arguments)
        lifecycle_port.assert_called_once()
    finally:
        arming_done.set()
        observer_thread.join(2)
    if case != 'callback':
        assert status == 0, f'GUI launcher returned {status} before a clean close'
    assert observed == [case], observed
    from metor.ui.gui.app import MetorApp

    assert isinstance(observed_app, MetorApp)
    assert observed_app._stopped
    assert observed_app.controller.client is None
    assert observed_app.controller.interactions.prompt is None
    worker = observed_app.controller._worker
    if worker is not None:
        worker.join(2)
        assert not worker.is_alive()
    if case == 'callback':
        assert status != 0, status
        print('INSTALLED_GUI_CALLBACK_FAILURE_OK')
    else:
        assert status == 0, status
        assert observed_app.controller.lifecycle.exit_ready
        print('INSTALLED_GUI_CLOSE_OK', case)


def main() -> None:
    """Create fresh data roots before any child imports Metor or the toolkit.

    Args:
        None
    Returns:
        None
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', choices=('empty', 'picker', 'callback'))
    arguments = parser.parse_args()
    if arguments.worker is not None:
        _worker(arguments.worker)
        return
    if os.environ.get('SDL_VIDEODRIVER') in {'dummy', 'offscreen'}:
        raise RuntimeError('Installed GUI native smoke requires a window display.')
    if os.name != 'nt' and not (
        os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')
    ):
        raise RuntimeError('Installed GUI native smoke requires a window display.')
    with tempfile.TemporaryDirectory(prefix='metor-gui-launch-') as directory:
        root = Path(directory)
        for case in ('empty', 'picker', 'callback'):
            data_parent = root / case
            data_parent.mkdir()
            (data_parent / '.gui-smoke-owner').write_text(
                'isolated\n', encoding='utf-8'
            )
            environment = dict(os.environ)
            environment.pop('PYTHONPATH', None)
            environment.pop('METOR_DEVICE_CONFIG', None)
            environment.update(
                {
                    'METOR_DATA_DIR_PARENT': str(data_parent),
                    'KIVY_HOME': str(data_parent / 'kivy'),
                    'KIVY_NO_ARGS': '1',
                    'KIVY_NO_FILELOG': '1',
                    'KIVY_NO_CONSOLELOG': '1',
                    'KIVY_NO_CONFIG': '1',
                    'MESA_SHADER_CACHE_DISABLE': 'true',
                }
            )
            result = subprocess.run(
                [sys.executable, '-I', str(Path(__file__).resolve()), '--worker', case],
                cwd=data_parent,
                env=environment,
                capture_output=True,
                text=True,
                timeout=_WORKER_SECONDS,
                check=False,
            )
            marker = (
                'INSTALLED_GUI_CALLBACK_FAILURE_OK'
                if case == 'callback'
                else f'INSTALLED_GUI_CLOSE_OK {case}'
            )
            if case == 'callback':
                assert (
                    'Metor GUI could not start [event-loop]: RuntimeError.'
                    in result.stderr
                ), 'Callback failure lacked safe launcher diagnosis'
                assert _CALLBACK_SECRET not in result.stderr
            if result.returncode != 0 or marker not in result.stdout:
                raise RuntimeError(
                    f'Installed GUI {case} smoke failed: status={result.returncode}; '
                    f'launcher_diagnostic={"Metor GUI could not start" in result.stderr}'
                )
            print(marker, flush=True)
        assert not tuple(root.rglob('device.toml'))
    print('INSTALLED_GUI_REAL_LAUNCH_OK desktop')


if __name__ == '__main__':
    main()
