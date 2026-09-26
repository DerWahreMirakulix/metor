"""Independent console and graphical entry points for Metor."""

import ctypes
import os
import sys
from contextlib import redirect_stderr, redirect_stdout


_WINDOWS_MESSAGE_BOX_ERROR_ICON: int = 0x10


def main() -> None:
    """
    Runs the base CLI without importing an interactive frontend.

    Args:
        None

    Returns:
        None
    """
    argv: list[str] = sys.argv[1:]
    from metor.cli.entry import run_cli

    sys.exit(run_cli(argv))


def _run_gui_cli(argv: list[str]) -> int:
    """Enter the Base CLI through its public frontend selection path.

    Args:
        argv: GUI chat arguments.

    Returns:
        int: CLI exit status.
    """
    from metor.cli.entry import run_cli

    return run_cli(argv)


def gui_main() -> None:
    """Launch the GUI without a Windows console and report startup failure.

    Args:
        None

    Returns:
        None
    """
    argv: list[str] = ['chat', '--ui', 'gui', *sys.argv[1:]]
    if sys.platform != 'win32' or (sys.stdout is not None and sys.stderr is not None):
        sys.exit(_run_gui_cli(argv))

    # pythonw-backed GUI scripts have no standard streams. Keep CLI and toolkit
    # diagnostics bounded to a sink and show a fixed native failure message.
    status: int = 1
    with open(os.devnull, 'w', encoding='utf-8') as sink:
        with redirect_stdout(sink), redirect_stderr(sink):
            try:
                status = _run_gui_cli(argv)
            except BaseException:
                status = 1
    if status != 0:
        ctypes.windll.user32.MessageBoxW(
            None,
            'Metor GUI could not start. Run metor chat --ui gui from PowerShell for diagnostics.',
            'Metor GUI',
            _WINDOWS_MESSAGE_BOX_ERROR_ICON,
        )
    sys.exit(status)


if __name__ == '__main__':
    main()
