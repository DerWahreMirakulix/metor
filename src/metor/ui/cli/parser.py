"""
Module providing the CLI argument parser.
Isolates argparse configuration from the application execution logic.
"""

import argparse
from typing import List, Optional, Tuple

from metor.data import ProfileManager


class CliParser:
    """Constructs and executes the command-line argument parser."""

    @staticmethod
    def parse(
        argv: Optional[List[str]] = None,
    ) -> Tuple[argparse.Namespace, List[str]]:
        """
        Configures the argument parser and parses the given argv inputs.

        Args:
            argv (Optional[List[str]]): The argument vector excluding the program name, or None to use sys.argv.

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
        parser.add_argument(
            '--locked',
            action='store_true',
            help='Start the daemon in locked mode until unlocked over IPC',
        )
        parser.add_argument(
            '--plaintext',
            action='store_true',
            help='Create a local plaintext profile without password protection',
        )
        parser.add_argument(
            '--startup-session-auth-stdin',
            action='store_true',
            help=argparse.SUPPRESS,
        )
        start_daemon_group = parser.add_mutually_exclusive_group()
        start_daemon_group.add_argument(
            '--start-daemon',
            dest='start_daemon',
            action='store_true',
            help='Override chat daemon autostart policy and start a missing local daemon.',
        )
        start_daemon_group.add_argument(
            '--no-start-daemon',
            dest='start_daemon',
            action='store_false',
            help='Override chat daemon autostart policy and keep missing daemons explicit.',
        )
        parser.set_defaults(start_daemon=None)

        parser.add_argument('command', nargs='?', default='quickstart')
        parser.add_argument('subcommand', nargs='?')
        parser.add_argument('extra', nargs='*')

        args: argparse.Namespace
        unknown: List[str]
        args, unknown = parser.parse_known_args(argv)
        args.extra.extend(unknown)

        return args, args.extra
