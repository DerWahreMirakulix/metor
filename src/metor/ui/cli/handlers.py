"""
Module containing execution logic for complex CLI commands.
Isolates interactive prompts and subsystem orchestration from the generic router.
"""

import sys
import shutil
import getpass
from typing import List

from metor.core import KeyManager, TorManager
from metor.core.api import TransCode
from metor.core.daemon import Daemon
from metor.data import HistoryManager, ContactManager, MessageManager, SqlManager
from metor.data.profile import ProfileManager
from metor.ui import Theme, Translator
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
        Injects the UI logger callbacks to enforce UI-Agnostic Core domains.

        Args:
            pm (ProfileManager): The active profile configuration.

        Returns:
            None
        """
        if pm.is_remote():
            msg, _ = Translator.get(TransCode.DAEMON_REMOTE_NO_START)
            print(msg)
            return
        if pm.is_daemon_running():
            msg, _ = Translator.get(
                TransCode.DAEMON_ALREADY_RUNNING, {'profile': pm.profile_name}
            )
            print(msg)
            return

        startup_msg, _ = Translator.get(
            TransCode.DAEMON_STARTING, {'profile': pm.profile_name}
        )
        print(startup_msg)

        prompt, _ = Translator.get(TransCode.ENTER_MASTER_PASSWORD)
        password: str = getpass.getpass(prompt)

        if not password:
            msg, _ = Translator.get(TransCode.DAEMON_EMPTY_PASSWORD)
            print(msg)
            return

        # Secure directory initialization before accessing any databases
        pm.initialize()

        # Inversion of Control: Define UI printing logic here and inject it into Data and Core layers
        def sql_log_cb(line: str) -> None:
            sys.stdout.write(f'\r\033[K{Theme.CYAN}[SQL-LOG]{Theme.RESET} {line}\n')
            sys.stdout.flush()

        def tor_log_cb(line: str) -> None:
            sys.stdout.write(f'\r\033[K{Theme.CYAN}[TOR-LOG]{Theme.RESET} {line}\n')
            sys.stdout.flush()

        def status_cb(line: str) -> None:
            sys.stdout.write(f'{line}\n')
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

        daemon: Daemon = Daemon(pm, km, tm, cm, hm, mm, status_callback=status_cb)
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
            msg, _ = Translator.get(
                TransCode.PROFILE_NOT_FOUND, {'profile': pm.profile_name}
            )
            print(msg)
            return

        if not pm.is_daemon_running():
            msg, _ = Translator.get(TransCode.DAEMON_OFFLINE)
            print(msg)
            return

        chat: Chat = Chat(pm)
        chat.run()

    @staticmethod
    def handle_cleanup() -> None:
        """
        Executes OS-level process cleanup, clears daemon locks, and reports the result.
        Strictly ignores remote profiles as cleanup is a host-local OS operation.

        Args:
            None

        Returns:
            None
        """
        msg, _ = Translator.get(TransCode.CLEANUP_START)
        print(msg)
        killed: int = ProcessManager.cleanup_processes()

        for profile_name in ProfileManager.get_all_profiles():
            temp_pm: ProfileManager = ProfileManager(profile_name)
            if not temp_pm.is_remote():
                temp_pm.clear_daemon_port()

        result_msg, _ = Translator.get(TransCode.CLEANUP_COMPLETE, {'killed': killed})
        print(result_msg)

    @staticmethod
    def handle_purge(is_nuke_remote: bool) -> None:
        """
        Permanently destroys all local data and optionally sends self-destruct commands to remote daemons.

        Args:
            is_nuke_remote (bool): Flag indicating if remote profiles should be signaled to self-destruct.

        Returns:
            None
        """
        message, _ = Translator.get(TransCode.PURGE_WARNING)
        if is_nuke_remote:
            remote_warn, _ = Translator.get(TransCode.PURGE_WARNING_REMOTE)
            message += f' {remote_warn}'

        print(message)
        prompt, _ = Translator.get(TransCode.PURGE_PROMPT)
        confirmation: str = input(prompt)

        if confirmation.strip().lower() == 'yes':
            if is_nuke_remote:
                remotes: List[str] = [
                    p
                    for p in ProfileManager.get_all_profiles()
                    if ProfileManager(p).is_remote()
                ]
                if not CommandHandlers._nuke_remote_profiles(remotes):
                    abort_msg, _ = Translator.get(TransCode.PURGE_ABORTED)
                    print(abort_msg)
                    return

            ProcessManager.cleanup_processes()
            if Constants.DATA.exists():
                shutil.rmtree(str(Constants.DATA))
                complete_msg, _ = Translator.get(TransCode.PURGE_COMPLETE)
                print(complete_msg)
        else:
            abort_msg, _ = Translator.get(TransCode.PURGE_ABORTED)
            print(abort_msg)

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
        warning_msg, _ = Translator.get(TransCode.REMOTE_NUKE_WARNING)
        print(warning_msg)
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
                success_msg, _ = Translator.get(
                    TransCode.REMOTE_NUKE_SUCCESS, {'profile': r}
                )
                print(success_msg)

        if failed_remotes:
            fail_msg, _ = Translator.get(
                TransCode.REMOTE_NUKE_FAILED,
                {'failed_remotes': f'{Theme.RESET}, {Theme.CYAN}'.join(failed_remotes)},
            )
            print(f'\n{fail_msg}\n')

            prompt, _ = Translator.get(TransCode.REMOTE_NUKE_OVERRIDE)
            override: str = input(prompt)
            if override.strip().lower() != 'y':
                return False
        return True
