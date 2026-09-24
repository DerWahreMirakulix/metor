"""General CLI entry point for commands and versioned frontend selection.

The module validates host configuration before dispatching Base-owned commands.
For interactive chat it selects a frontend by identifier and launches it only
through the public client contract; it does not implement a frontend itself.
"""

import argparse
import os
import sys
from pathlib import Path
from typing import List

from metor.client import (
    FrontendLaunchError,
    LoadedFrontend,
    load_frontend,
    valid_frontend_profile_name,
)
from metor.data.profile.catalog import (
    resolve_initial_profile,
    get_all_profiles,
    get_unavailable_profile_names,
)
from metor.data import ProfileManager, SettingKey, Settings
from metor.cli.dispatcher import CliDispatcher
from metor.cli.handlers import CommandHandlers
from metor.cli.help import Help
from metor.cli.parser import CliParser
from metor.cli.theme import Theme
from metor.versioning import APP_VERSION
from metor.application import initialize_runtime_environment


def run_cli(argv: List[str]) -> int:
    """
    Runs the general command-line entry against the given argument vector.

    Validates configuration integrity before command dispatch and resolves an
    interactive frontend without importing its implementation into Base.

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

    if args.command == 'chat' and args.chat_help:
        print(Help.show_chat_launcher_help())
        return 0
    if args.command == 'chat' and extra:
        sys.stderr.write('Unexpected chat arguments.\n')
        print(Help.show_chat_launcher_help())
        return 2
    if args.command == 'chat' and getattr(args, 'list_uis', False):
        return CommandHandlers.handle_list_frontends()
    if args.command in ('help',) or (
        args.command == 'quickstart' and args.help_requested
    ):
        print(Help.show_main_help())
        return 0
    if args.help_requested:
        print(Help.show_command_help(args.command, args.subcommand))
        return 0
    if args.command == 'quickstart':
        print(Help.show_quick_start())
        return 0

    initialize_runtime_environment()
    if args.startup_session_auth_stdin and not args.non_interactive:
        sys.stderr.write(
            '--startup-session-auth-stdin requires daemon --non-interactive.\n'
        )
        return 2
    if args.command == 'chat' and not extra:
        selected_frontend: str = (
            args.ui
            or os.environ.get('METOR_UI')
            or Settings.get_str(
                SettingKey.DEFAULT_UI,
                persist_defaults=False,
            )
        )
        requested_device = args.device_config
        if requested_device is None and selected_frontend == 'gui':
            requested_device = os.environ.get('METOR_DEVICE_CONFIG') or None
        if (
            requested_device is not None or args.simulator
        ) and selected_frontend != 'gui':
            sys.stderr.write('Device options require the gui frontend.\n')
            return 2
        if requested_device is not None:
            if not requested_device.strip():
                sys.stderr.write('Device configuration path must not be empty.\n')
                return 2
            args.device_config = str(Path(requested_device).absolute())
        try:
            loaded_frontend: LoadedFrontend = load_frontend(selected_frontend)
        except FrontendLaunchError as exc:
            sys.stderr.write(f'{exc}\n')
            return 2
        args.loaded_frontend = loaded_frontend

    if args.command == 'chat':
        if args.profile is not None and not valid_frontend_profile_name(args.profile):
            sys.stderr.write('Invalid profile name.\n')
            return 2
        initial = resolve_initial_profile(args.profile)
        if selected_frontend == 'gui':
            try:
                pm_for_gui = ProfileManager(initial) if initial is not None else None
            except (ValueError, OSError):
                pm_for_gui = None
            return CommandHandlers.handle_chat(
                pm_for_gui,
                args.start_daemon,
                selected_frontend,
                loaded_frontend=args.loaded_frontend,
                device_config=args.device_config,
                simulator=args.simulator,
                debug=args.debug,
                initial_profile=initial,
            )
        if initial is None:
            message = (
                'Some profiles are unavailable or damaged. Repair storage or choose another profile.\n'
                if get_unavailable_profile_names()
                else 'No profiles exist yet. Create one with `metor profiles add NAME`.\n'
                if not get_all_profiles()
                else 'Select a profile with -p NAME or set a default.\n'
            )
            sys.stderr.write(message)
            return 1
        if initial not in get_all_profiles():
            sys.stderr.write(f"Profile '{initial}' does not exist.\n")
            return 1
        args.profile = initial

    pm: ProfileManager = ProfileManager(args.profile)
    if args.command != 'daemon':
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
