"""
Module serving as the main entry point for the Metor application.
Executes the CLI parser and delegates to the command dispatcher.
"""

import argparse
from typing import List

from metor.data.profile import ProfileManager
from metor.ui.cli import CliParser, CliDispatcher


def main() -> None:
    """
    Invokes the Metor application.

    Args:
        None

    Returns:
        None
    """
    args: argparse.Namespace
    extra: List[str]
    args, extra = CliParser.parse()
    pm: ProfileManager = ProfileManager(args.profile)

    dispatcher: CliDispatcher = CliDispatcher(args, extra, pm)
    dispatcher.dispatch()


if __name__ == '__main__':
    main()
