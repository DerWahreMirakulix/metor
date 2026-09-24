"""Lazy GUI entry point; validation precedes toolkit, host and driver work."""

from dataclasses import replace
import os
import logging
import sys
import time
import traceback
from pathlib import Path
from typing import TextIO

from metor.client import FRONTEND_LAUNCH_CONTRACT_VERSION, FrontendLaunchContext
from metor.ui.gui.platform import DeviceConfigurationError, read_configuration
from metor.versioning import APP_VERSION


class GuiEntry:
    """Versioned installed frontend provider without eager Kivy initialization."""

    contract_version: int = FRONTEND_LAUNCH_CONTRACT_VERSION

    def __call__(self, context: FrontendLaunchContext) -> int:
        """Starts one native application after strict requested-mode validation.

        Args:
            context: Public launch/host context.
        Returns:
            int: Native application status or safe startup failure.
        """
        try:
            configuration = read_configuration(
                context.device_config, context.simulator, context.platform
            )
        except DeviceConfigurationError as exc:
            sys.stderr.write(f'{exc}\n')
            return 2
        os.environ['KIVY_NO_ARGS'] = '1'
        os.environ['KIVY_NO_FILELOG'] = '1'
        os.environ['KIVY_NO_CONFIG'] = '1'
        os.environ['KIVY_NO_CONSOLELOG'] = '1'
        os.environ['KIVY_LOG_MODE'] = 'PYTHON'
        toolkit_logger = logging.getLogger('kivy')
        toolkit_logger.addHandler(logging.NullHandler())
        toolkit_logger.propagate = False
        # UI Automation registration must precede the HWND's first visible frame.
        if sys.platform == 'win32':
            os.environ['KCFG_GRAPHICS_WINDOW_STATE'] = 'hidden'
        if (
            sys.platform.startswith('linux')
            and not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))
            and os.environ.get('SDL_VIDEODRIVER') != 'offscreen'
        ):
            sys.stderr.write(
                'No graphical display is available.\n'
                'Use the Terminal UI or configure a supported device display.\n'
            )
            return 2
        original_stderr = sys.stderr
        started = time.monotonic()
        stage = 'toolkit-import'
        try:
            from metor.ui.gui.app import MetorApp

            stage = 'platform-activation'
            active_context = replace(
                context, platform=configuration.activate_platform(context.platform)
            )
            stage = 'app-build'
            app = MetorApp(active_context, configuration)
            stage = 'event-loop'
            app.run()
            if not app.controller.lifecycle.exit_ready:
                self._report_fatal(
                    original_stderr,
                    'event-loop',
                    'unexpected toolkit return',
                    context.debug,
                    elapsed=time.monotonic() - started,
                )
                return 1
            return app.exit_status
        except BaseException as exc:
            reason = exc.__class__.__name__
            if isinstance(exc, SystemExit) and type(exc.code) is int:
                reason = f'toolkit exited with status {exc.code}'
            self._report_fatal(
                original_stderr,
                stage,
                reason,
                context.debug,
                exc,
                elapsed=time.monotonic() - started,
            )
            return 1

    @staticmethod
    def _report_fatal(
        stream: TextIO,
        stage: str,
        reason: str,
        debug: bool,
        error: BaseException | None = None,
        *,
        elapsed: float = 0.0,
    ) -> None:
        """Write one safe fatal summary to the original caller-provided stream.

        Args:
            stream: Stderr captured before toolkit initialization.
            stage: Non-secret startup or event-loop phase.
            reason: Exception class or stable outcome name.
            debug: Whether safe stack locations were requested.
            error: Optional exception; message and frame locals stay private.
            elapsed: Bounded launch duration for opt-in diagnostics.
        Returns:
            None
        """
        try:
            stream.write(f'Metor GUI could not start [{stage}]: {reason}.\n')
            if debug:
                stream.write(
                    f'  Metor {APP_VERSION}; GUI module {Path(__file__).name}; '
                    f'elapsed {elapsed:.3f}s\n'
                )
            if debug and error is not None:
                frames = traceback.extract_tb(error.__traceback__)[-8:]
                for frame in frames:
                    stream.write(
                        f'  {Path(frame.filename).name}:{frame.lineno} '
                        f'in {frame.name}\n'
                    )
            stream.flush()
        except OSError:
            pass


launch = GuiEntry()
