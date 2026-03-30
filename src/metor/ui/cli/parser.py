"""
Module providing the CLI argument parser.
Isolates argparse configuration from the application execution logic.
"""

import argparse
from typing import List, Tuple

from metor.data.profile import ProfileManager


class CliParser:
    """Constructs and executes the command-line argument parser."""

    @staticmethod
    def parse() -> Tuple[argparse.Namespace, List[str]]:
        """
        Configures the argument parser and parses the sys.argv inputs.

        Args:
            None

        Returns:
            Tuple[argparse.Namespace, List[str]]: The parsed known arguments and a list of extra/unknown arguments.
        """
        parser: argparse.ArgumentParser = argparse.ArgumentParser(
            prog='metor', add_help=False
        )
        parser.add_argument(
            '-p', '--profile', default=ProfileManager.load_default_profile()
        )
        parser.add_argument(
            '--remote', action='store_true', help='Set profile as remote client'
        )
        parser.add_argument('--port', type=int, help='Set static daemon port')

        parser.add_argument('command', nargs='?', default='quickstart')
        parser.add_argument('subcommand', nargs='?')
        parser.add_argument('extra', nargs='*')

        args, unknown = parser.parse_known_args()
        args.extra.extend(unknown)

        return args, args.extra
