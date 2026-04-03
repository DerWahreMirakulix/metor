"""
Module serving as the main entry point for the Metor application.
Executes the CLI parser, validates systemic configuration integrity,
and delegates to the command dispatcher.
"""

import argparse
import sys
from typing import List

from metor.data.settings import Settings
from metor.data.profile import ProfileManager
from metor.ui import Theme
from metor.ui.cli import CliParser, CliDispatcher


def main() -> None:
    """
    Invokes the Metor application. Validates configuration integrity before dispatch.
    Implements Fail-Fast architecture to prevent runtime crashes on corrupted JSON.

    Args:
        None

    Returns:
        None
    """
    args: argparse.Namespace
    extra: List[str]
    args, extra = CliParser.parse()

    try:
        Settings.validate_integrity()
    except ValueError as e:
        sys.stderr.write(f'{Theme.RED}Global Settings Error:{Theme.RESET} {e}\n')
        sys.exit(1)

    pm: ProfileManager = ProfileManager(args.profile)

    try:
        pm.validate_integrity()
    except ValueError as e:
        sys.stderr.write(
            f"{Theme.RED}Profile '{pm.profile_name}' Error:{Theme.RESET} {e}\n"
        )
        sys.exit(1)

    dispatcher: CliDispatcher = CliDispatcher(args, extra, pm)
    try:
        dispatcher.dispatch()
    except (EOFError, KeyboardInterrupt):
        sys.stderr.write('\n')
        sys.exit(130)


if __name__ == '__main__':
    main()
