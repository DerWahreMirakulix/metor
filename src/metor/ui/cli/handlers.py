"""
Module containing execution logic for complex CLI commands.
Isolates interactive prompts and subsystem orchestration from the generic router.
"""

import sys
import shutil
from typing import List, Dict, Optional, Union

from metor.core.api import EventType, JsonValue
from metor.application import (
    CorruptedDaemonStorageError,
    DaemonStatus,
    InvalidDaemonPasswordError,
    configure_daemon_runtime_logging,
    run_managed_daemon,
)
from metor.data.profile import ProfileManager
from metor.ui import PromptAbortedError, Theme, Translator, prompt_hidden, prompt_text
from metor.ui.chat import Chat
from metor.utils import Constants, ProcessManager

from metor.data.profile import (
    ProfileOperationResult,
    ProfileOperationType,
    ProfileSecurityMode,
)
from metor.ui.cli.proxy import CliProxy


class CommandHandlers:
    """Encapsulates the execution logic for multi-step CLI commands."""

    @staticmethod
    def _format_daemon_status(
        status: DaemonStatus, params: Dict[str, JsonValue]
    ) -> str:
        """
        Formats local daemon startup statuses for the CLI.

        Args:
            status (DaemonStatus): The local daemon startup status.
            params (Dict[str, JsonValue]): Supplemental formatting values.

        Returns:
            str: The rendered CLI line.
        """
        if status is DaemonStatus.LOCKED_MODE:
            return 'Daemon running in LOCKED mode... Waiting for IPC unlock.'

        onion: str = str(params.get('onion', ''))
        port: str = str(params.get('port', 'unknown'))
        return (
            f'Daemon active. Onion: {Theme.YELLOW}{onion}{Theme.RESET}.onion | '
            f'IPC Port: {Theme.YELLOW}{port}{Theme.RESET}'
        )

    @staticmethod
    def handle_daemon(pm: ProfileManager, start_locked: bool = False) -> None:
        """
        Authenticates the user and starts the background Daemon subsystem.
        Injects the UI logger callbacks to enforce UI-Agnostic Core domains.

        Args:
            pm (ProfileManager): The active profile configuration.
            start_locked (bool): Whether to expose only the IPC server until unlock.

        Returns:
            None
        """
        if pm.is_remote():
            print('Cannot start a daemon on a remote profile!')
            return
        if pm.is_daemon_running():
            print(f"Daemon for profile '{pm.profile_name}' is already running!")
            return

        print(f"Starting daemon for profile '{pm.profile_name}'...")

        if start_locked and pm.uses_plaintext_storage():
            print('Plaintext profiles cannot be started in locked mode.')
            return

        password: Optional[str] = None
        if pm.uses_encrypted_storage() and not start_locked:
            try:
                password = prompt_hidden(
                    f'{Theme.GREEN}Enter Master Password: {Theme.RESET}'
                )
            except PromptAbortedError:
                return

            if not password:
                print('Master password cannot be empty.')
                return

        # Inversion of Control: Define UI printing logic here and inject it into Data and Core layers
        def sql_log_cb(line: str) -> None:
            """Writes one SQLCipher diagnostic line to stdout with its log tag."""
            sys.stdout.write(f'\r\033[K{Theme.CYAN}[SQL-LOG]{Theme.RESET} {line}\n')
            sys.stdout.flush()

        def tor_log_cb(line: str) -> None:
            """Writes one Tor process diagnostic line to stdout with its log tag."""
            sys.stdout.write(f'\r\033[K{Theme.CYAN}[TOR-LOG]{Theme.RESET} {line}\n')
            sys.stdout.flush()

        def status_cb(
            code: Union[EventType, DaemonStatus],
            params: Optional[Dict[str, JsonValue]] = None,
        ) -> None:
            """Translates and prints one daemon startup status event to stdout."""
            if params is None:
                params = {}
            if isinstance(code, EventType):
                msg, _ = Translator.get(code, params)
            else:
                msg = CommandHandlers._format_daemon_status(code, params)
            sys.stdout.write(f'{msg}\n')
            sys.stdout.flush()

        configure_daemon_runtime_logging(sql_log_cb, tor_log_cb)

        if start_locked:
            try:
                run_managed_daemon(
                    pm,
                    password=password,
                    start_locked=True,
                    status_callback=status_cb,
                )
            except InvalidDaemonPasswordError:
                msg, _ = Translator.get(EventType.INVALID_PASSWORD)
                print(msg)
            except CorruptedDaemonStorageError:
                msg, _ = Translator.get(EventType.DB_CORRUPTED)
                print(
                    f"{msg}\nYou need to run 'metor purge' or manually delete the storage.db."
                )
            return

        try:
            run_managed_daemon(
                pm,
                password=password,
                start_locked=False,
                status_callback=status_cb,
            )
        except InvalidDaemonPasswordError:
            msg, _ = Translator.get(EventType.INVALID_PASSWORD)
            print(msg)
        except CorruptedDaemonStorageError:
            msg, _ = Translator.get(EventType.DB_CORRUPTED)
            print(
                f"{msg}\nYou need to run 'metor purge' or manually delete the storage.db."
            )

    @staticmethod
    def handle_profile_security_migration(
        name: str,
        target_mode: ProfileSecurityMode,
    ) -> ProfileOperationResult:
        """
        Interactively migrates one local profile between encrypted and plaintext storage.

        Args:
            name (str): Target profile name.
            target_mode (ProfileSecurityMode): The requested storage mode.

        Returns:
            ProfileOperationResult: Structured local outcome for the CLI layer.
        """
        pm: ProfileManager = ProfileManager(name)
        if not pm.exists():
            return ProfileManager.migrate_profile_security(name, target_mode)

        current_mode: ProfileSecurityMode = pm.get_security_mode()
        if current_mode is target_mode:
            return ProfileManager.migrate_profile_security(name, target_mode)

        if target_mode is ProfileSecurityMode.PLAINTEXT:
            print(
                f'This will store the profile database and local keys in '
                f'{Theme.RED}plaintext at rest{Theme.RESET}.'
            )
            try:
                confirm: str = prompt_text("Type 'yes' to continue: ")
            except PromptAbortedError:
                return ProfileOperationResult(
                    False,
                    ProfileOperationType.SECURITY_MIGRATION_FAILED,
                    {'profile': name, 'reason': 'Security migration aborted.'},
                )
            if confirm.strip().lower() != 'yes':
                return ProfileOperationResult(
                    False,
                    ProfileOperationType.SECURITY_MIGRATION_FAILED,
                    {'profile': name, 'reason': 'Security migration aborted.'},
                )

        current_password: Optional[str] = None
        if current_mode is ProfileSecurityMode.ENCRYPTED:
            try:
                current_password = prompt_hidden(
                    f'{Theme.GREEN}Enter Current Master Password: {Theme.RESET}'
                )
            except PromptAbortedError:
                return ProfileOperationResult(
                    False,
                    ProfileOperationType.SECURITY_MIGRATION_FAILED,
                    {'profile': name, 'reason': 'Security migration aborted.'},
                )
            if not current_password:
                return ProfileOperationResult(
                    False,
                    ProfileOperationType.SECURITY_MIGRATION_FAILED,
                    {
                        'profile': name,
                        'reason': 'Current master password cannot be empty.',
                    },
                )

        new_password: Optional[str] = None
        if target_mode is ProfileSecurityMode.ENCRYPTED:
            try:
                new_password = prompt_hidden(
                    f'{Theme.GREEN}Enter New Master Password: {Theme.RESET}'
                )
            except PromptAbortedError:
                return ProfileOperationResult(
                    False,
                    ProfileOperationType.SECURITY_MIGRATION_FAILED,
                    {'profile': name, 'reason': 'Security migration aborted.'},
                )
            if not new_password:
                return ProfileOperationResult(
                    False,
                    ProfileOperationType.SECURITY_MIGRATION_FAILED,
                    {
                        'profile': name,
                        'reason': 'New master password cannot be empty.',
                    },
                )

            try:
                confirm_password: str = prompt_hidden(
                    f'{Theme.GREEN}Confirm New Master Password: {Theme.RESET}'
                )
            except PromptAbortedError:
                return ProfileOperationResult(
                    False,
                    ProfileOperationType.SECURITY_MIGRATION_FAILED,
                    {'profile': name, 'reason': 'Security migration aborted.'},
                )
            if new_password != confirm_password:
                return ProfileOperationResult(
                    False,
                    ProfileOperationType.SECURITY_MIGRATION_FAILED,
                    {'profile': name, 'reason': 'New master passwords do not match.'},
                )

        return ProfileManager.migrate_profile_security(
            name,
            target_mode,
            current_password=current_password,
            new_password=new_password,
        )

    @staticmethod
    def handle_chat(pm: ProfileManager) -> None:
        """
        Validates daemon state and launches the interactive Chat UI.

        Args:
            pm (ProfileManager): The active profile configuration.

        Returns:
            None
        """
        if not pm.exists():
            print(f"Profile '{pm.profile_name}' does not exist.")
            return

        if not pm.is_daemon_running():
            msg, _ = Translator.get(EventType.DAEMON_OFFLINE)
            print(msg)
            return

        chat: Chat = Chat(pm)
        chat.run()

    @staticmethod
    def handle_cleanup(force: bool = False) -> None:
        """
        Executes OS-level process cleanup, clears daemon state, and reports the result.
        Strictly ignores remote profiles as cleanup is a host-local OS operation.

        Args:
            force (bool): Enables an explicit rescue scan when runtime-state files are missing or corrupted.

        Returns:
            None
        """
        if force:
            print('Cleaning up Metor processes and daemon state (force mode)...')
        else:
            print('Cleaning up Metor processes and daemon state...')

        killed: int = ProcessManager.cleanup_processes(force=force)
        cleared_runtime_state: int = 0

        for profile_name in ProfileManager.get_all_profiles():
            temp_pm: ProfileManager = ProfileManager(profile_name)
            if not temp_pm.is_remote():
                had_runtime_state: bool = (
                    temp_pm.paths.get_daemon_port_file().exists()
                    or temp_pm.paths.get_daemon_pid_file().exists()
                )
                temp_pm.clear_daemon_port()
                if had_runtime_state:
                    cleared_runtime_state += 1

        if killed > 0:
            print(
                'Cleanup completed. Managed processes were terminated and daemon state was cleared.'
            )
            return

        if cleared_runtime_state > 0:
            print('Cleanup completed. Daemon state was cleared.')
            return

        if force:
            print('Cleanup completed. No managed processes or daemon state were found.')
            return

        print(
            "Cleanup completed. No managed processes or daemon state were found. If the local runtime state is damaged, try 'metor cleanup --force'."
        )

    @staticmethod
    def handle_purge(is_nuke_remote: bool) -> None:
        """
        Permanently destroys all local data and optionally sends self-destruct commands to remote daemons.

        Args:
            is_nuke_remote (bool): Flag indicating if remote profiles should be signaled to self-destruct.

        Returns:
            None
        """
        message: str = (
            f'You are about to {Theme.RED}PERMANENTLY WIPE{Theme.RESET} '
            'the entire Metor directory!'
        )
        if is_nuke_remote:
            remote_warn: str = (
                f'This includes {Theme.RED}ALL REMOTE PROFILES{Theme.RESET} '
                'and their data!'
            )
            message += f' {remote_warn}'

        print(message)
        try:
            confirmation: str = prompt_text("Type 'yes' to proceed: ")
        except PromptAbortedError:
            print(f'{Theme.YELLOW}Purge aborted.{Theme.RESET}')
            return

        if confirmation.strip().lower() == 'yes':
            if is_nuke_remote:
                remotes: List[str] = [
                    p
                    for p in ProfileManager.get_all_profiles()
                    if ProfileManager(p).is_remote()
                ]
                if not CommandHandlers._nuke_remote_profiles(remotes):
                    print('Purge aborted.')
                    return

            ProcessManager.cleanup_processes()
            if Constants.DATA.exists():
                shutil.rmtree(str(Constants.DATA))
                print(f'{Theme.GREEN}Purge complete. All data destroyed.{Theme.RESET}')
        else:
            print(f'{Theme.YELLOW}Purge aborted.{Theme.RESET}')

    @staticmethod
    def _nuke_remote_profiles(profile_names: List[str]) -> bool:
        """
        Sends the self-destruct command to the specified remote profiles.
        If any fail, prompts the user for confirmation to proceed anyway.

        Args:
            profile_names (List[str]): List of remote profile names to nuke.

        Returns:
            bool: True if successful or user overridden, False if aborted.
        """
        print(
            f'Data shredding may be {Theme.YELLOW}INEFFECTIVE ON MODERN{Theme.RESET} '
            'SSDs due to wear-leveling.\n'
        )
        failed_remotes: List[str] = []

        for r in profile_names:
            pm: ProfileManager = ProfileManager(r)
            if not pm.is_remote():
                print(
                    f"Profile '{r}' is a local profile. {Theme.YELLOW}Ignoring --nuke-remote.{Theme.RESET}"
                )
                continue

            proxy: CliProxy = CliProxy(pm)
            res: str = proxy.nuke_daemon()
            if 'Error' in res or 'Failed' in res:
                failed_remotes.append(r)
            else:
                print(f"Remote daemon for profile '{r}' nuked successfully.")

        if failed_remotes:
            failed_text: str = (
                Theme.CYAN
                + f'{Theme.RESET}, {Theme.CYAN}'.join(failed_remotes)
                + Theme.RESET
            )
            print(
                f'\n{Theme.RED}Failed to reach remote daemons for profiles:{Theme.RESET} '
                f'{failed_text}\n'
            )

            try:
                override: str = prompt_text(
                    'You will lock yourself out of these remotes! Proceed with local wipe anyway? y/N: '
                )
            except PromptAbortedError:
                return False
            if override.strip().lower() != 'y':
                return False
        return True
