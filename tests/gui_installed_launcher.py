"""Exercise the wheel-installed CLI and native GUI through deliberate close.

Use ``--case callback`` to run only the isolated callback-failure worker.
"""

import argparse
import builtins
import json
import os
from pathlib import Path
import re
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
_OBSERVATION_MARKER = 'INSTALLED_GUI_CALLBACK_OBSERVATION '
_OBSERVATION_LIMIT = 4
_OBSERVATION_MAX_CHARS = 2048
_CATEGORY_MAX_CHARS = 80
_FATAL_STAGES = frozenset(
    {'toolkit-import', 'platform-activation', 'app-build', 'event-loop', 'app-cleanup'}
)
_SOURCE_NAME = re.compile(
    r'(?:kivy|metor)/[A-Za-z0-9_./-]+\.py|tests/gui_installed_launcher\.py'
)


def _safe_category(value: object) -> bool:
    """Accept only bounded built-in exception names or fixed launcher outcomes.

    Args:
        value: Candidate label from a worker observation.
    Returns:
        bool: Whether the label can be repeated in public test evidence.
    """
    if type(value) is not str or len(value) > _CATEGORY_MAX_CHARS:
        return False
    builtin = vars(builtins).get(value)
    return bool(
        (isinstance(builtin, type) and issubclass(builtin, BaseException))
        or value == 'unexpected toolkit return'
        or re.fullmatch(r'toolkit exited with status -?[0-9]{1,20}', value)
    )


def _source_locations(
    error: BaseException, installed_root: Path, origin: str
) -> list[dict[str, object]]:
    """Retain only real installed source sites or this exact test fixture.

    Args:
        error: Exception whose traceback may contain private frame data.
        installed_root: Current isolated wheel environment.
        origin: Whether these frames belong to the outer error or its cause.
    Returns:
        list[dict[str, object]]: Up to four verified relative source sites.
    """
    sites: list[dict[str, object]] = []
    frame = error.__traceback__
    fixture = Path(__file__).resolve()
    while frame is not None:
        path = Path(frame.tb_frame.f_code.co_filename).resolve()
        if path == fixture:
            source = 'tests/gui_installed_launcher.py'
        elif path.is_file() and path.is_relative_to(installed_root):
            relative = path.relative_to(installed_root).parts
            source = (
                '/'.join(relative[relative.index('site-packages') + 1 :])
                if 'site-packages' in relative
                else ''
            )
        else:
            source = ''
        if _SOURCE_NAME.fullmatch(source) and type(frame.tb_lineno) is int:
            sites.append({'origin': origin, 'source': source, 'line': frame.tb_lineno})
        frame = frame.tb_next
    return sites[-_OBSERVATION_LIMIT:]


def _read_callback_observation(stdout: str) -> dict[str, object] | None:
    """Read one bounded, typed observation from the isolated worker.

    Args:
        stdout: Captured worker stdout, never included raw in failures.
    Returns:
        dict[str, object] | None: Safe observation or None for invalid transport.
    """
    records = [
        line[len(_OBSERVATION_MARKER) :]
        for line in stdout.splitlines()
        if line.startswith(_OBSERVATION_MARKER)
    ]
    if len(records) != 1 or len(records[0]) > _OBSERVATION_MAX_CHARS:
        return None
    try:
        value = json.loads(records[0])
    except (ValueError, TypeError):
        return None
    if type(value) is not dict or set(value) != {
        'case',
        'injection_observed',
        'application_status',
        'cleanup_complete',
        'diagnostics',
    }:
        return None
    if (
        value['case'] != 'callback'
        or type(value['injection_observed']) is not bool
        or type(value['application_status']) is not int
        or type(value['cleanup_complete']) is not bool
        or type(value['diagnostics']) is not list
        or len(value['diagnostics']) > _OBSERVATION_LIMIT
    ):
        return None
    for diagnostic in value['diagnostics']:
        if (
            type(diagnostic) is not dict
            or set(diagnostic)
            != {
                'stage',
                'reason',
                'exception_chain',
                'locations',
            }
            or type(diagnostic['stage']) is not str
            or diagnostic['stage'] not in _FATAL_STAGES
            or not _safe_category(diagnostic['reason'])
            or type(diagnostic['exception_chain']) is not list
            or len(diagnostic['exception_chain']) > _OBSERVATION_LIMIT
            or any(
                not _safe_category(category)
                for category in diagnostic['exception_chain']
            )
            or type(diagnostic['locations']) is not list
            or len(diagnostic['locations']) > 2 * _OBSERVATION_LIMIT
        ):
            return None
        for location in diagnostic['locations']:
            if (
                type(location) is not dict
                or set(location) != {'origin', 'source', 'line'}
                or type(location['origin']) is not str
                or location['origin'] not in {'outer', 'cause'}
                or type(location['source']) is not str
                or not _SOURCE_NAME.fullmatch(location['source'])
                or any(
                    part in {'', '.', '..'} for part in location['source'].split('/')
                )
                or type(location['line']) is not int
                or not 0 < location['line'] < 100000
            ):
                return None
    return value


def _verify_callback_result(
    result: subprocess.CompletedProcess[str],
) -> dict[str, object]:
    """Require injection, native failure, safe stderr, and confirmed cleanup.

    Args:
        result: One isolated installed callback worker result.
    Returns:
        dict[str, object]: Bounded verified evidence for the callback case.
    """
    if _CALLBACK_SECRET in result.stdout or _CALLBACK_SECRET in result.stderr:
        raise AssertionError('gui-smoke-secret-leak')
    if 'INSTALLED_GUI_CALLBACK_INJECTED' not in result.stdout.splitlines():
        raise AssertionError('gui-smoke-injection-missing')
    observation = _read_callback_observation(result.stdout)
    if observation is None:
        raise AssertionError('gui-smoke-observation-invalid')
    if (
        result.returncode != 0
        or 'INSTALLED_GUI_CALLBACK_FAILURE_OK' not in result.stdout.splitlines()
        or not observation['injection_observed']
        or observation['application_status'] == 0
        or not observation['cleanup_complete']
    ):
        raise AssertionError(f'gui-smoke-outcome-mismatch {observation}')
    diagnostics = observation['diagnostics']
    assert isinstance(diagnostics, list)
    if len(diagnostics) != 1:
        raise AssertionError(f'gui-smoke-diagnostic-mismatch {observation}')
    diagnostic = diagnostics[0]
    assert isinstance(diagnostic, dict)
    reason = diagnostic['reason']
    chain = diagnostic['exception_chain']
    locations = diagnostic['locations']
    assert isinstance(locations, list)
    injection_origin = 'cause' if reason == 'SystemError' else 'outer'
    has_injection_site = any(
        location['origin'] == injection_origin
        and location['source'] == 'tests/gui_installed_launcher.py'
        for location in locations
    )
    if diagnostic['stage'] != 'event-loop' or not (
        (
            (reason == 'RuntimeError' and chain == [])
            or (reason == 'SystemError' and chain == ['RuntimeError'])
        )
        and has_injection_site
    ):
        raise AssertionError(f'gui-smoke-diagnostic-mismatch {observation}')
    expected_line = f'Metor GUI could not start [event-loop]: {reason}.'
    if expected_line not in result.stderr.splitlines():
        raise AssertionError(f'gui-smoke-stderr-mismatch {observation}')
    return observation


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
    diagnostics: list[dict[str, object]] = []
    started = time.monotonic()

    from metor.ui.gui.launcher import GuiEntry

    original_report = GuiEntry._report_fatal

    def observe_fatal(
        stream: object,
        stage: str,
        reason: str,
        debug: bool,
        error: BaseException | None = None,
        *,
        elapsed: float = 0.0,
    ) -> None:
        """Record only safe categories while preserving the actual fatal report.

        Args:
            stream: The launcher's original stderr destination.
            stage: Internal launch phase.
            reason: The launcher's safe reason.
            debug: Whether bounded source locations are enabled.
            error: Optional exception whose messages remain private.
            elapsed: Launch duration passed to the original reporter.
        Returns:
            None
        """
        if len(diagnostics) < _OBSERVATION_LIMIT:
            try:
                chain: list[str] = []
                seen: set[int] = set()
                current = (
                    error.__cause__ or error.__context__ if error is not None else None
                )
                locations = (
                    _source_locations(error, installed_root, 'outer')
                    if error is not None
                    else []
                )
                if current is not None:
                    locations.extend(
                        _source_locations(current, installed_root, 'cause')
                    )
                while current is not None and len(chain) < _OBSERVATION_LIMIT:
                    if id(current) in seen:
                        break
                    seen.add(id(current))
                    category = GuiEntry._safe_reason(current)
                    chain.append(category if _safe_category(category) else 'Exception')
                    current = current.__cause__ or current.__context__
                safe_reason = (
                    GuiEntry._safe_reason(error)
                    if error is not None
                    else 'unexpected toolkit return'
                    if reason == 'unexpected toolkit return'
                    else 'Exception'
                )
                diagnostics.append(
                    {
                        'stage': stage if stage in _FATAL_STAGES else 'unknown',
                        'reason': safe_reason
                        if _safe_category(safe_reason)
                        else 'Exception',
                        'exception_chain': chain,
                        'locations': locations,
                    }
                )
            except Exception:
                diagnostics.append(
                    {
                        'stage': stage if stage in _FATAL_STAGES else 'unknown',
                        'reason': 'Exception',
                        'exception_chain': [],
                        'locations': [],
                    }
                )
        original_report(stream, stage, reason, debug, error, elapsed=elapsed)

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
            print('INSTALLED_GUI_CALLBACK_INJECTED', flush=True)
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
        with (
            patch.object(
                native_lifecycle, 'create_desktop_lifecycle_source', return_value=None
            ) as lifecycle_port,
            patch.object(GuiEntry, '_report_fatal', staticmethod(observe_fatal)),
        ):
            status = run_cli(arguments)
        lifecycle_port.assert_called_once()
    finally:
        arming_done.set()
        observer_thread.join(2)
        assert not observer_thread.is_alive(), 'GUI observer thread did not stop'
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
        print(
            _OBSERVATION_MARKER
            + json.dumps(
                {
                    'case': case,
                    'injection_observed': observed == [case],
                    'application_status': status,
                    'cleanup_complete': observed_app._stopped
                    and observed_app.controller.client is None
                    and observed_app.controller.interactions.prompt is None
                    and not observer_thread.is_alive()
                    and (worker is None or not worker.is_alive()),
                    'diagnostics': diagnostics,
                },
                sort_keys=True,
            ),
            flush=True,
        )
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
    parser.add_argument(
        '--case',
        choices=('empty', 'picker', 'callback'),
        help='Run one isolated installed GUI case; default runs all cases.',
    )
    arguments = parser.parse_args()
    if arguments.worker is not None and arguments.case is not None:
        parser.error('--case cannot be combined with --worker')
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
        cases = (
            (arguments.case,)
            if arguments.case is not None
            else (
                'empty',
                'picker',
                'callback',
            )
        )
        for case in cases:
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
            observation = (
                _verify_callback_result(result) if case == 'callback' else None
            )
            if result.returncode != 0 or marker not in result.stdout.splitlines():
                raise RuntimeError(
                    f'Installed GUI {case} smoke failed: status={result.returncode}; '
                    f'launcher_diagnostic={"Metor GUI could not start" in result.stderr}'
                )
            if observation is not None:
                print(
                    _OBSERVATION_MARKER + json.dumps(observation, sort_keys=True),
                    flush=True,
                )
            print(marker, flush=True)
        assert not tuple(root.rglob('device.toml'))
    print(
        'INSTALLED_GUI_REAL_LAUNCH_OK desktop'
        if arguments.case is None
        else f'INSTALLED_GUI_CASE_OK {arguments.case}'
    )


if __name__ == '__main__':
    main()
