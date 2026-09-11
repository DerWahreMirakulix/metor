"""
Module providing the CLI argument parser.
Isolates argparse configuration from the application execution logic.
"""

import argparse
from typing import List, Optional, Tuple


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
        parser.add_argument('-p', '--profile')
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
        parser.add_argument('--version', action='store_true')
        parser.add_argument('command', nargs='?', default='quickstart')
        parser.add_argument('subcommand', nargs='?')
        parser.add_argument('extra', nargs='*')

        args: argparse.Namespace
        unknown: List[str]
        args, unknown = parser.parse_known_args(argv)
        args.extra.extend(unknown)

        args.ui = None
        args.list_uis = False
        args.chat_help = False
        args.start_daemon = None
        if args.command == 'chat':
            chat_parser = argparse.ArgumentParser(prog='metor chat', add_help=False)
            chat_parser.add_argument('--ui')
            chat_parser.add_argument('--list-uis', action='store_true')
            start_daemon_group = chat_parser.add_mutually_exclusive_group()
            start_daemon_group.add_argument(
                '--start-daemon', dest='start_daemon', action='store_true'
            )
            start_daemon_group.add_argument(
                '--no-start-daemon', dest='start_daemon', action='store_false'
            )
            chat_parser.set_defaults(start_daemon=None)
            chat_parser.add_argument(
                '-h', '--help', dest='chat_help', action='store_true'
            )
            chat_args, chat_unknown = chat_parser.parse_known_args(args.extra)
            args.ui = chat_args.ui
            args.list_uis = chat_args.list_uis
            args.chat_help = chat_args.chat_help
            args.start_daemon = chat_args.start_daemon
            args.extra = chat_unknown
            args.subcommand = chat_unknown[0] if chat_unknown else None

        return args, args.extra
