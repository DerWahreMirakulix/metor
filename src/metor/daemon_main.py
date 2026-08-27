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
    InvalidDaemonPasswordError,
    PlaintextLockedDaemonError,
    cleanup_local_runtime,
    run_managed_daemon,
)
from metor.data import ProfileManager, SettingKey, Settings


def _read_startup_session_auth_password_from_stdin() -> Optional[str]:
    """
    Reads one startup-only session-auth password from a detached parent pipe.

    Args:
        None

    Returns:
        Optional[str]: The provided password, or None when absent.
    """
    password: str = sys.stdin.readline().rstrip('\r\n')
    if not password:
        return None
    return password


def _build_parser() -> argparse.ArgumentParser:
    """
    Builds the minimal metor-daemon argument parser.

    Args:
        None

    Returns:
        argparse.ArgumentParser: The configured parser.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog='metor-daemon',
        description='Headless daemon-only entry point for the Metor application.',
    )
    parser.add_argument(
        '-p',
        '--profile',
        default=ProfileManager.load_default_profile(),
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

    if not pm.exists():
        print(f"Profile '{profile}' does not exist.")
        return 1

    try:
        Settings.validate_integrity()
        pm.validate_integrity()
    except ValueError as exc:
        sys.stderr.write(f'{exc}\n')
        return 1

    if pm.is_remote():
        print('Cannot start a daemon on a remote profile!')
        return 1

    if pm.is_daemon_running():
        print(f"Daemon for profile '{pm.profile_name}' is already running!")
        return 0

    if start_locked and pm.uses_plaintext_storage():
        print('Plaintext profiles cannot be started in locked mode.')
        return 1

    if not start_locked and pm.uses_encrypted_storage():
        sys.stderr.write(
            "Encrypted profiles require '--locked' startup in headless mode. "
            "Use 'metor daemon' for interactive password entry.\n"
        )
        return 1

    session_auth_password: Optional[str] = None
    if not start_locked and pm.config.get_bool(SettingKey.REQUIRE_LOCAL_AUTH):
        if not startup_session_auth_stdin:
            sys.stderr.write(
                'This profile requires local session auth. '
                'Pass --startup-session-auth-stdin in headless mode.\n'
            )
            return 1
        session_auth_password = _read_startup_session_auth_password_from_stdin()
        if session_auth_password is None:
            print('Aborted.')
            return 1

    try:
        run_managed_daemon(
            pm,
            password=None,
            session_auth_password=session_auth_password,
            start_locked=start_locked,
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
        "If the local runtime state is damaged, try 'metor-daemon cleanup --force'."
    )
    return 0


def main() -> None:
    """
    Parses the headless daemon argv and dispatches the requested command.

    Args:
        None

    Returns:
        None
    """
    args: argparse.Namespace = _build_parser().parse_args()

    try:
        exit_code: int
        if args.command == 'cleanup':
            exit_code = _run_cleanup(force=args.force)
        elif args.command == 'unlock':
            sys.stderr.write(
                "Unlock requires the terminal UI. Run 'metor unlock' instead.\n"
            )
            exit_code = 1
        else:
            exit_code = _run_daemon(
                profile=args.profile,
                start_locked=args.locked,
                startup_session_auth_stdin=args.startup_session_auth_stdin,
            )
    except (EOFError, KeyboardInterrupt):
        sys.stderr.write('\n')
        sys.exit(130)

    sys.exit(exit_code)


if __name__ == '__main__':
    main()
