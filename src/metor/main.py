"""
Module serving as the main entry point for the Metor application.
Resolves the active frontend from the --ui argument, the METOR_UI environment
variable, or the default terminal frontend, then delegates execution.
"""

import os
import sys
from typing import List, Optional, Tuple

from metor.ui import get_frontend, get_registered_frontends
from metor.ui.registry import register_frontend
from metor.ui.terminal.cli.entry import run_cli


def _extract_ui_argument(argv: List[str]) -> Tuple[Optional[str], List[str]]:
    """
    Strips --ui / --ui=<id> tokens from argv and returns the requested id.

    Args:
        argv (List[str]): The raw argument vector excluding the program name.

    Returns:
        Tuple[Optional[str], List[str]]: The requested frontend id (or None when absent) and the filtered argv.
    """
    ui_id: Optional[str] = None
    filtered: List[str] = []
    index: int = 0
    while index < len(argv):
        token: str = argv[index]
        if token == '--ui':
            if index + 1 < len(argv):
                ui_id = argv[index + 1]
                index += 2
                continue
            index += 1
            continue
        if token.startswith('--ui='):
            ui_id = token[len('--ui=') :]
            index += 1
            continue
        filtered.append(token)
        index += 1
    return ui_id, filtered


def _resolve_frontend_id(ui_argument: Optional[str]) -> str:
    """
    Resolves the effective frontend identifier with env fallback to 'terminal'.

    Args:
        ui_argument (Optional[str]): The --ui flag value, or None when absent.

    Returns:
        str: The effective frontend identifier.
    """
    if ui_argument is not None:
        return ui_argument
    return os.environ.get('METOR_UI', 'terminal')


def main() -> None:
    """
    Selects the active frontend and delegates the filtered argv to it.

    Args:
        None

    Returns:
        None
    """
    if 'terminal' not in get_registered_frontends():
        register_frontend('terminal', run_cli)

    ui_argument: Optional[str]
    argv: List[str]
    ui_argument, argv = _extract_ui_argument(sys.argv[1:])

    ui_id: str = _resolve_frontend_id(ui_argument)

    try:
        frontend = get_frontend(ui_id)
    except KeyError:
        registered: str = ', '.join(sorted(get_registered_frontends())) or 'none'
        sys.stderr.write(
            f"Unknown frontend '{ui_id}'. Registered frontends: {registered}\n"
        )
        sys.exit(2)

    sys.exit(frontend(argv))


if __name__ == '__main__':
    main()
