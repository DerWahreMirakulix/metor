"""
Module providing the headless daemon-only CLI entry point.
Deliberately avoids the UI layer: imports only core, data, application, and
utils domains so daemon operation never pulls in themes or CLI parsing.
"""

import argparse
import sys
from typing import Optional

from metor.application import (
    CorruptedDaemonStorageError,
    DaemonProfileMissingError,
    DaemonStartPreparation,
    InvalidDaemonPasswordError,
    PlaintextLockedDaemonError,
    RemoteDaemonProfileError,
    cleanup_local_runtime,
    run_managed_daemon,
    prepare_managed_daemon_start,
)
from metor.application.runtime.daemon import read_startup_secret
from metor.data import ProfileManager


def _build_parser() -> argparse.ArgumentParser:
    """
    Builds the minimal noninteractive `metor daemon` child parser.

    Args:
        None

    Returns:
        argparse.ArgumentParser: The configured parser.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog='metor',
        description='Noninteractive daemon child entry for the Metor application.',
    )
    parser.add_argument(
        '-p',
        '--profile',
        default=None,
    )
    parser.add_argument(
        '--locked',
        action='store_true',
        help='Start the daemon in locked mode until unlocked over IPC',
    )
    parser.add_argument(
        '--startup-session-auth-stdin',
        action='store_true',
        help=argparse.SUPPRESS,
    )
    parser.add_argument('--daemon-child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument(
        'command',
        nargs='?',
        default='daemon',
        choices=('daemon', 'cleanup', 'unlock'),
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Force a rescue scan during cleanup when runtime-state files are missing.',
    )
    return parser


def _run_daemon(
    profile: str,
    start_locked: bool,
    startup_session_auth_stdin: bool,
) -> int:
    """
    Starts one foreground managed daemon without any UI dependency.

    Args:
        profile (str): The active profile name.
        start_locked (bool): Whether to expose only the IPC server until unlock.
        startup_session_auth_stdin (bool): Whether plaintext session-auth input should be read from stdin.

    Returns:
        int: The process exit code.
    """
    pm: ProfileManager = ProfileManager(profile)
    try:
        preparation: DaemonStartPreparation = prepare_managed_daemon_start(
            pm,
            start_locked=start_locked,
        )
    except (DaemonProfileMissingError, RemoteDaemonProfileError) as exc:
        print(exc)
        return 1
    except PlaintextLockedDaemonError:
        print('Plaintext profiles cannot be started in locked mode.')
        return 1
    except ValueError as exc:
        sys.stderr.write(f'{exc}\n')
        return 1

    if preparation.already_running:
        print(f"Daemon for profile '{pm.profile_name}' is already running!")
        return 0

    if not start_locked and preparation.encrypted:
        sys.stderr.write(
            "Encrypted profiles require '--locked' startup in headless mode. "
            "Use 'metor daemon' for interactive password entry.\n"
        )
        return 1

    session_auth_password: Optional[str] = None
    if preparation.session_auth_required:
        if not startup_session_auth_stdin:
            sys.stderr.write(
                'This profile requires local session auth. '
                'Pass --startup-session-auth-stdin in headless mode.\n'
            )
            return 1
        try:
            session_auth_password = read_startup_secret(sys.stdin)
        except ValueError as exc:
            sys.stderr.write(f'{exc}\n')
            return 1
        if session_auth_password is None:
            print('Aborted.')
            return 1

    try:
        run_managed_daemon(
            pm,
            password=None,
            session_auth_password=session_auth_password,
            start_locked=start_locked,
            preparation=preparation,
        )
    except InvalidDaemonPasswordError:
        print('Invalid master password.')
        return 1
    except CorruptedDaemonStorageError:
        print(
            "Storage database is corrupted. Run 'metor purge' "
            'or manually delete the storage.db.'
        )
        return 1
    except PlaintextLockedDaemonError:
        print('Plaintext profiles cannot be started in locked mode.')
        return 1
    except ValueError as exc:
        print(f'Daemon startup failed: {exc}')
        return 1
    return 0


def _run_cleanup(force: bool) -> int:
    """
    Executes OS-level process cleanup and clears daemon state.

    Args:
        force (bool): Enables an explicit rescue scan when runtime-state files are missing or corrupted.

    Returns:
        int: The process exit code.
    """
    if force:
        print('Cleaning up Metor processes and daemon state (force mode)...')
    else:
        print('Cleaning up Metor processes and daemon state...')

    result = cleanup_local_runtime(force=force)

    if result.killed_processes > 0:
        print(
            'Cleanup completed. Managed processes were terminated '
            'and daemon state was cleared.'
        )
        return 0

    if result.cleared_runtime_state > 0:
        print('Cleanup completed. Daemon state was cleared.')
        return 0

    if force:
        print('Cleanup completed. No managed processes or daemon state were found.')
        return 0

    print(
        'Cleanup completed. No managed processes or daemon state were found. '
        "If the local runtime state is damaged, try 'metor cleanup --force'."
    )
    return 0


def run(argv: Optional[list[str]] = None) -> int:
    """Runs the noninteractive daemon adapter and returns its exit status."""
    args: argparse.Namespace = _build_parser().parse_args(argv)
    from metor.application import initialize_runtime_environment

    initialize_runtime_environment()

    try:
        if args.command == 'cleanup':
            return _run_cleanup(force=args.force)
        if args.command == 'unlock':
            sys.stderr.write(
                "Unlock requires credential interaction. Run 'metor unlock' instead.\n"
            )
            return 1
        profile: str = args.profile or ProfileManager.load_default_profile()
        return _run_daemon(
            profile=profile,
            start_locked=args.locked,
            startup_session_auth_stdin=args.startup_session_auth_stdin,
        )
    except (EOFError, KeyboardInterrupt):
        sys.stderr.write('\n')
        return 130


def main() -> None:
    """
    Parses the headless daemon argv and dispatches the requested command.

    Args:
        None

    Returns:
        None
    """
    sys.exit(run())


if __name__ == '__main__':
    main()
