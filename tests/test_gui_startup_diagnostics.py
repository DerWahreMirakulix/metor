"""GUI fatal stderr and explicit termination classification regressions."""

from contextlib import redirect_stderr
from io import StringIO
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from metor.client import FrontendLaunchContext
from metor.ui.gui.launcher import GuiEntry


class GuiStartupDiagnosticsTests(unittest.TestCase):
    """Exercise the production launcher without opening a native window."""

    def _launch_with_app(
        self,
        exit_ready: bool,
        failure: BaseException | None = None,
        cleanup_failure: BaseException | None = None,
    ) -> tuple[int, str]:
        """Run the launcher with an inert toolkit app at its import boundary.

        Args:
            exit_ready: Whether a deliberate GUI close completed.
            failure: Optional event-loop failure.
            cleanup_failure: Optional cleanup failure.
        Returns:
            tuple[int, str]: Exit code and caller-visible stderr.
        """
        module = ModuleType('metor.ui.gui.app')

        class TestApp:
            """Inert app exposing the actual launcher termination fields."""

            def __init__(self, *_args: object, **_kwargs: object) -> None:
                """Create a completed or aborted event loop state.

                Args:
                    _args: App constructor inputs.
                    _kwargs: App constructor options.
                Returns:
                    None
                """
                self.controller = SimpleNamespace(
                    lifecycle=SimpleNamespace(exit_ready=exit_ready)
                )
                self.exit_status = 0

            def on_stop(self) -> None:
                """Record cleanup even after an abnormal toolkit return.

                Args:
                    None
                Returns:
                    None
                """
                self_outer.stops += 1
                if cleanup_failure is not None:
                    raise cleanup_failure

            def run(self) -> None:
                """Return as a mocked event loop.

                Args:
                    None
                Returns:
                    None
                """
                if failure is not None:
                    raise failure

        self_outer = self
        self.stops = 0
        module.MetorApp = TestApp  # type: ignore[attr-defined]
        configuration = SimpleNamespace(activate_platform=lambda value: value)
        sink = StringIO()
        with (
            patch.dict(sys.modules, {'metor.ui.gui.app': module}),
            patch(
                'metor.ui.gui.launcher.read_configuration', return_value=configuration
            ),
            patch.dict(os.environ, {'SDL_VIDEODRIVER': 'offscreen'}),
            redirect_stderr(sink),
        ):
            status = GuiEntry()(FrontendLaunchContext(None, SimpleNamespace()))
        return status, sink.getvalue()

    def test_deliberate_first_run_close_succeeds(self) -> None:
        """A first-run GUI can close normally without authentication.

        Args:
            None
        Returns:
            None
        """
        status, stderr = self._launch_with_app(True)
        self.assertEqual(status, 0)
        self.assertEqual(stderr, '')
        self.assertEqual(self.stops, 1)

    def test_unexpected_event_loop_return_is_visible_failure(self) -> None:
        """A toolkit return without deliberate Close reports a nonzero stop.

        Args:
            None
        Returns:
            None
        """
        status, stderr = self._launch_with_app(False)
        self.assertEqual(status, 1)
        self.assertIn('Metor GUI could not start [event-loop]', stderr)
        self.assertEqual(self.stops, 1)

    def test_event_loop_failures_release_app_and_redact_details(self) -> None:
        """An exception or nonnumeric toolkit exit still runs cleanup once.

        Args:
            None
        Returns:
            None
        """
        for failure, expected in (
            (RuntimeError('password-secret'), 'RuntimeError'),
            (SystemExit('password-secret'), 'SystemExit'),
            (SystemExit(7), 'toolkit exited with status 7'),
        ):
            with self.subTest(failure=type(failure).__name__):
                status, stderr = self._launch_with_app(False, failure)
                self.assertEqual(status, 1)
                self.assertIn(
                    f'Metor GUI could not start [event-loop]: {expected}', stderr
                )
                self.assertNotIn('password-secret', stderr)
                self.assertEqual(self.stops, 1)

    def test_cleanup_failure_is_reported_even_on_normal_return(self) -> None:
        """A native teardown failure cannot be mistaken for a clean exit.

        Args:
            None
        Returns:
            None
        """
        status, stderr = self._launch_with_app(
            True, cleanup_failure=RuntimeError('password-secret')
        )
        self.assertEqual(status, 1)
        self.assertIn('Metor GUI could not start [app-cleanup]: RuntimeError', stderr)
        self.assertNotIn('password-secret', stderr)
        self.assertEqual(self.stops, 1)

    def test_real_subprocess_import_error_preserves_stderr_and_redacts_exception(
        self,
    ) -> None:
        """The production import boundary never prints an arbitrary exception secret.

        Args:
            None
        Returns:
            None
        """
        script = """import builtins, os, sys
from metor.client import FrontendLaunchContext
from metor.ui.gui.launcher import GuiEntry
original = builtins.__import__
original_stderr = sys.stderr
def fail(name, *args, **kwargs):
    if name == 'metor.ui.gui.app':
        original('kivy.logger')
        print('stderr-preserved', sys.stderr is original_stderr)
        raise RuntimeError('synthetic-secret-sentinel')
    return original(name, *args, **kwargs)
builtins.__import__ = fail
sys.exit(GuiEntry()(FrontendLaunchContext(None, object(), debug=True)))
"""
        with TemporaryDirectory() as root:
            environment = os.environ.copy()
            environment['METOR_DATA_DIR_PARENT'] = root
            environment['SDL_VIDEODRIVER'] = 'offscreen'
            result = subprocess.run(
                [sys.executable, '-I', '-c', script],
                cwd=Path(root),
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            'Metor GUI could not start [toolkit-import]: RuntimeError.', result.stderr
        )
        self.assertIn('launcher.py:', result.stderr)
        self.assertIn('stderr-preserved True', result.stdout)
        self.assertNotIn('synthetic-secret-sentinel', result.stderr)

    def test_debug_redacts_foreign_stack_locations_and_exception_class(self) -> None:
        """Untrusted callback filenames and custom class names never reach stderr.

        Args:
            None
        Returns:
            None
        """
        secret = 'password-secret'
        namespace: dict[str, object] = {}
        exec(
            compile('def fail():\n    raise RuntimeError()', secret, 'exec'), namespace
        )
        try:
            namespace['fail']()
        except RuntimeError as error:
            sink = StringIO()
            GuiEntry._report_fatal(sink, 'event-loop', 'RuntimeError', True, error)
            self.assertNotIn(secret, sink.getvalue())
            self.assertNotIn('fail', sink.getvalue())
        custom = type(secret, (Exception,), {})()
        self.assertEqual(GuiEntry._safe_reason(custom), 'Exception')

    def test_default_subprocess_import_failure_has_safe_stderr(self) -> None:
        """Fatal import failure is visible without opting into debug detail.

        Args:
            None
        Returns:
            None
        """
        script = """import builtins, sys
from metor.client import FrontendLaunchContext
from metor.ui.gui.launcher import GuiEntry
original = builtins.__import__
def fail(name, *args, **kwargs):
    if name == 'metor.ui.gui.app':
        original('kivy.logger')
        raise RuntimeError('synthetic-secret-sentinel')
    return original(name, *args, **kwargs)
builtins.__import__ = fail
sys.exit(GuiEntry()(FrontendLaunchContext(None, object())))
"""
        with TemporaryDirectory() as root:
            environment = os.environ.copy()
            environment['METOR_DATA_DIR_PARENT'] = root
            environment['SDL_VIDEODRIVER'] = 'offscreen'
            result = subprocess.run(
                [sys.executable, '-I', '-c', script],
                cwd=Path(root),
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            'Metor GUI could not start [toolkit-import]: RuntimeError.', result.stderr
        )
        self.assertNotIn('synthetic-secret-sentinel', result.stderr)
        self.assertNotIn('launcher.py:', result.stderr)
