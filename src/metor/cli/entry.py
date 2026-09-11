"""
Module providing the terminal frontend entry point.
Executes the CLI parser, validates systemic configuration integrity,
and delegates to the command dispatcher.
"""

import argparse
import os
import sys
from typing import List

from metor.client import FrontendLaunchError, LoadedFrontend, load_frontend
from metor.data import ProfileManager, SettingKey, Settings
from metor.cli import CliDispatcher, CliParser, Help, Theme
from metor.cli.handlers import CommandHandlers
from metor.versioning import APP_VERSION


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

    if args.version or args.command == 'version':
        print(APP_VERSION)
        return 0

    help_token: bool = args.subcommand in ('-h', '--help') or any(
        token in ('-h', '--help') for token in extra
    )
    if args.command == 'chat' and getattr(args, 'chat_help', False):
        print(Help.show_chat_launcher_help())
        return 0
    if args.command == 'chat' and getattr(args, 'list_uis', False):
        return CommandHandlers.handle_list_frontends()
    if args.command in ('-h', '--help', 'help') or (
        args.command == 'quickstart' and help_token
    ):
        print(Help.show_main_help())
        return 0
    if help_token:
        print(Help.show_command_help(args.command, args.subcommand))
        return 0
    if args.command == 'quickstart':
        print(Help.show_quick_start())
        return 0

    if args.command == 'chat' and not extra:
        selected_frontend: str = (
            args.ui
            or os.environ.get('METOR_UI')
            or Settings.get_str(
                SettingKey.DEFAULT_UI,
                persist_defaults=False,
            )
        )
        try:
            loaded_frontend: LoadedFrontend = load_frontend(selected_frontend)
        except FrontendLaunchError as exc:
            sys.stderr.write(f'{exc}\n')
            return 2
        args.loaded_frontend = loaded_frontend

    pm: ProfileManager = ProfileManager(args.profile)
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
