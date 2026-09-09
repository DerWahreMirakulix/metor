"""
Module providing the terminal frontend entry point.
Executes the CLI parser, validates systemic configuration integrity,
and delegates to the command dispatcher.
"""

import argparse
import sys
from typing import List

from metor.data import ProfileManager, Settings
from metor.ui import Theme
from metor.ui.cli import CliDispatcher, CliParser


def run_cli(argv: List[str]) -> int:
    """
    Runs the terminal frontend against the given argument vector.
    Validates configuration integrity before dispatch. Implements Fail-Fast
    architecture to prevent runtime crashes on corrupted JSON.

    Args:
        argv (List[str]): The raw argument vector excluding the program name.

    Returns:
        int: The process exit code.
    """
    args: argparse.Namespace
    extra: List[str]
    args, extra = CliParser.parse(argv)

    help_only: bool = args.command in ('quickstart', 'help', '-h', '--help')
    pm: ProfileManager = ProfileManager(args.profile)

    if not help_only:
        try:
            Settings.validate_integrity()
        except ValueError as e:
            sys.stderr.write(f'{Theme.RED}Global Settings Error:{Theme.RESET} {e}\n')
            return 1

        try:
            pm.validate_integrity()
        except ValueError as e:
            sys.stderr.write(
                f"{Theme.RED}Profile '{pm.profile_name}' Error:{Theme.RESET} {e}\n"
            )
            return 1

    dispatcher: CliDispatcher = CliDispatcher(args, extra, pm)
    try:
        return dispatcher.dispatch()
    except (EOFError, KeyboardInterrupt):
        sys.stderr.write('\n')
        return 130
