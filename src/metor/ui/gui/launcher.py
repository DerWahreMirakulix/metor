"""Lazy GUI entry point; validation precedes toolkit, host and driver work."""

from dataclasses import replace
import os
import sys

from metor.client import FRONTEND_LAUNCH_CONTRACT_VERSION, FrontendLaunchContext
from metor.ui.gui.platform import DeviceConfigurationError, read_configuration


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
        from metor.ui.gui.app import MetorApp

        active_context = replace(
            context, platform=configuration.activate_platform(context.platform)
        )
        app = MetorApp(active_context, configuration)
        app.run()
        return app.exit_status


launch = GuiEntry()
