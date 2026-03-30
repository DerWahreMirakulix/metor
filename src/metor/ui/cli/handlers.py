"""
Module containing execution logic for complex CLI commands.
Isolates interactive prompts and subsystem orchestration from the generic router.
"""

import sys
import shutil
import getpass
from typing import List

from metor.core.daemon import Daemon
from metor.core.key import KeyManager
from metor.core.tor import TorManager
from metor.data.profile import ProfileManager
from metor.data import HistoryManager, ContactManager, MessageManager
from metor.data.sql import SqlManager
from metor.ui import Theme
from metor.ui.chat import Chat
from metor.utils import Constants, ProcessManager

# Local Package Imports
from metor.ui.cli.proxy import CliProxy


class CommandHandlers:
    """Encapsulates the execution logic for multi-step CLI commands."""

    @staticmethod
    def handle_daemon(pm: ProfileManager) -> None:
        """
        Authenticates the user and starts the background Daemon subsystem.

        Args:
            pm (ProfileManager): The active profile configuration.

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
        password: str = getpass.getpass(
            f'{Theme.CYAN}Enter Master Password: {Theme.RESET}'
        )

        if not password:
            print('Master password cannot be empty.')
            return

        # Inversion of Control: Define UI printing logic here and inject it into Data and Core layers
        def sql_log_cb(line: str) -> None:
            sys.stdout.write(f'\r\033[K{Theme.CYAN}[SQL-LOG]{Theme.RESET} {line}\n')
            sys.stdout.flush()

        def tor_log_cb(line: str) -> None:
            sys.stdout.write(f'\r\033[K{Theme.CYAN}[TOR-LOG]{Theme.RESET} {line}\n')
            sys.stdout.flush()

        SqlManager.set_log_callback(sql_log_cb)
        TorManager.set_log_callback(tor_log_cb)

        km: KeyManager = KeyManager(pm, password)
        tm: TorManager = TorManager(pm, km)

        try:
            cm: ContactManager = ContactManager(pm, password)
            hm: HistoryManager = HistoryManager(pm, password)
            mm: MessageManager = MessageManager(pm, password)
        except ValueError:
            print(
                f'{Theme.RED}The database is corrupted from a previous crash or syntax error.{Theme.RESET}\n'
                "You need to run 'metor purge' or manually delete the storage.db."
            )
            return

        daemon: Daemon = Daemon(pm, km, tm, cm, hm, mm)
        daemon.run()

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
            print('The background daemon is not running or unreachable.')
            return

        chat: Chat = Chat(pm)
        chat.run()

    @staticmethod
    def handle_cleanup() -> None:
        """
        Executes OS-level process cleanup, clears daemon locks, and reports the result.

        Args:
            None

        Returns:
            None
        """
        print('Cleaning up Metor processes and locks...')
        killed: int = ProcessManager.cleanup_processes()

        for profile_name in ProfileManager.get_all_profiles():
            temp_pm: ProfileManager = ProfileManager(profile_name)
            temp_pm.clear_daemon_port()

        print(f'Killed {killed} Tor process(es) and cleared locks.')

    @staticmethod
    def handle_purge(is_nuke_remote: bool) -> None:
        """
        Permanently destroys all local data and optionally sends self-destruct commands to remote daemons.

        Args:
            is_nuke_remote (bool): Flag indicating if remote profiles should be signaled to self-destruct.

        Returns:
            None
        """
        message: str = f'{Theme.RED}You are about to PERMANENTLY wipe the entire Metor directory!{Theme.RESET}'
        if is_nuke_remote:
            message += f' {Theme.RED}This includes all remote profiles and their data!{Theme.RESET}'

        print(message)
        confirmation: str = input("Type 'yes' to proceed: ")

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
                print('Purge complete. All data destroyed.')
        else:
            print('Purge aborted.')

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
            f'{Theme.YELLOW}Data shredding may be ineffective on modern SSDs due to wear-leveling.{Theme.RESET}\n'
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
            print(
                '\n'
                f'Failed to reach remote daemons for profiles: '
                f'{Theme.CYAN}{f"{Theme.RESET}, {Theme.CYAN}".join(failed_remotes)}{Theme.RESET}'
                '\n'
            )
            override: str = input(
                'You will lock yourself out of these remotes! Proceed with local wipe anyway? y/N: '
            )
            if override.strip().lower() != 'y':
                return False
        return True
