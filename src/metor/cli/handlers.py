"""
Module containing execution logic for complex CLI commands.
Isolates interactive prompts and subsystem orchestration from the generic router.
"""

import os
import sys
from typing import List, Dict, Optional, Union

from metor.core.api import EventType, JsonValue
from metor.client import (
    FrontendLaunchContext,
    FrontendLaunchError,
    LoadedFrontend,
    discover_frontends,
    invoke_frontend,
    load_frontend,
)
from metor.application import (
    cleanup_local_runtime,
    CorruptedDaemonStorageError,
    DaemonProfileMissingError,
    DaemonStartPreparation,
    DaemonStatus,
    InvalidDaemonPasswordError,
    PlaintextLockedDaemonError,
    RemoteDaemonProfileError,
    configure_daemon_runtime_logging,
    create_local_frontend_host,
    read_startup_secret,
    prepare_managed_daemon_start,
    run_managed_daemon,
)
from metor.data import (
    ProfileManager,
    ProfileSecurityMode,
    SettingKey,
    Settings,
)
from metor.shared import escape_terminal_text
from metor.cli.prompt import (
    PromptAbortedError,
    PromptOutputSpacer,
    prompt_hidden,
    prompt_text,
)
from metor.cli.theme import Theme
from metor.cli.translations import Translator
from metor.cli.errors import format_safe_local_runtime_error
from metor.utils import Constants, ProcessManager
from metor.cli.proxy import CliProxy


def _prompt_hidden_optional(prompt: str) -> Optional[str]:
    """
    Prompts for hidden input while keeping module-local prompt patch hooks intact.

    Args:
        prompt (str): The rendered prompt text.

    Returns:
        Optional[str]: The entered text, or None when the input is empty.
    """
    value: str = prompt_hidden(prompt)
    if not value:
        return None
    return value


class CommandHandlers:
    """Encapsulates the execution logic for multi-step CLI commands."""

    @staticmethod
    def handle_list_frontends() -> int:
        """Lists installed frontend metadata without profile initialization.

        Args:
            None

        Returns:
            int: The resulting integer value.
        """
        try:
            installed = discover_frontends()
        except FrontendLaunchError as exc:
            sys.stderr.write(f'{exc}\n')
            return 2
        if not installed:
            print('No interactive Metor frontends are installed.')
            return 0
        for installed_id, descriptor in sorted(installed.items()):
            print(f'{installed_id}\t{descriptor.distribution}')
        return 0

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

        if status is DaemonStatus.RUNTIME_ERROR:
            message: str = str(
                params.get('message') or 'Unexpected daemon runtime error.'
            )
            return (
                f'{Theme.CYAN}[DAEMON-LOG]{Theme.RESET} {escape_terminal_text(message)}'
            )

        onion: str = str(params.get('onion', ''))
        port: str = str(params.get('port', 'unknown'))
        return (
            f'Daemon active. Onion: {Theme.YELLOW}'
            f'{escape_terminal_text(onion)}{Theme.RESET}.onion | '
            f'IPC Port: {Theme.YELLOW}{escape_terminal_text(port)}{Theme.RESET}'
        )

    @staticmethod
    def handle_daemon(
        pm: ProfileManager,
        start_locked: bool = False,
        startup_session_auth_stdin: bool = False,
        non_interactive: bool = False,
        chat_owner: tuple[int, float] | None = None,
    ) -> int:
        """
        Authenticates the user and starts the background Daemon subsystem.
        Injects the UI logger callbacks to enforce UI-Agnostic Core domains.

        Args:
            pm (ProfileManager): The active profile configuration.
            start_locked (bool): Whether to expose only the IPC server until unlock.
            startup_session_auth_stdin (bool): Whether plaintext session-auth input should be read from stdin instead of an interactive prompt.
            non_interactive (bool): Whether every terminal prompt must be disabled.

        Returns:
            int: Process-compatible daemon execution status.
        """
        try:
            preparation: DaemonStartPreparation = prepare_managed_daemon_start(
                pm,
                start_locked=start_locked,
            )
        except (DaemonProfileMissingError, RemoteDaemonProfileError) as exc:
            print(escape_terminal_text(str(exc)))
            return 1
        except PlaintextLockedDaemonError:
            print('Plaintext profiles cannot be started in locked mode.')
            return 1
        except ValueError as exc:
            print(format_safe_local_runtime_error(exc), file=sys.stderr)
            return 1

        if preparation.already_running:
            print(
                'Daemon for profile '
                f"'{escape_terminal_text(pm.profile_name)}' is already running!"
            )
            return 0

        if non_interactive and preparation.encrypted and not start_locked:
            sys.stderr.write(
                "Encrypted profiles require '--locked' in non-interactive mode.\n"
            )
            return 1
        if (
            non_interactive
            and preparation.session_auth_required
            and not startup_session_auth_stdin
        ):
            sys.stderr.write(
                'This profile requires local session auth. Pass '
                '--startup-session-auth-stdin in non-interactive mode.\n'
            )
            return 1

        print(
            f"Starting daemon for profile '{escape_terminal_text(pm.profile_name)}'..."
        )

        password: Optional[str] = None
        session_auth_password: Optional[str] = None
        output_spacer = PromptOutputSpacer()
        if preparation.encrypted and not start_locked:
            try:
                password = _prompt_hidden_optional(
                    f'{Theme.GREEN}Enter Master Password: {Theme.RESET}'
                )
                output_spacer.mark_prompt()
            except PromptAbortedError:
                return 1

            if password is None:
                print(output_spacer.format('Aborted.'))
                return 1
        elif preparation.session_auth_required:
            if startup_session_auth_stdin:
                try:
                    session_auth_password = read_startup_secret(sys.stdin)
                except ValueError as exc:
                    print(output_spacer.format(escape_terminal_text(str(exc))))
                    return 1
                if session_auth_password is None:
                    print('Aborted.')
                    return 1
            else:
                try:
                    session_auth_password = _prompt_hidden_optional(
                        f'{Theme.GREEN}Enter Session Auth Password: {Theme.RESET}'
                    )
                    output_spacer.mark_prompt()
                except PromptAbortedError:
                    return 1

                if session_auth_password is None:
                    print(output_spacer.format('Aborted.'))
                    return 1

        # Inversion of Control: Define UI printing logic here and inject it into Data and Core layers
        def sql_log_cb(line: str) -> None:
            """Writes one SQLCipher diagnostic line to stdout with its log tag.

            Args:
                line (str): The line input.

            Returns:
                None
            """
            sys.stdout.write(
                f'\r\033[K{Theme.CYAN}[SQL-LOG]{Theme.RESET} '
                f'{escape_terminal_text(line)}\n'
            )
            sys.stdout.flush()

        def tor_log_cb(line: str) -> None:
            """Writes one Tor process diagnostic line to stdout with its log tag.

            Args:
                line (str): The line input.

            Returns:
                None
            """
            sys.stdout.write(
                f'\r\033[K{Theme.CYAN}[TOR-LOG]{Theme.RESET} '
                f'{escape_terminal_text(line)}\n'
            )
            sys.stdout.flush()

        def status_cb(
            code: Union[EventType, DaemonStatus],
            params: Optional[Dict[str, JsonValue]] = None,
        ) -> None:
            """Translates and prints one daemon startup status event to stdout.

            Args:
                code (Union[EventType, DaemonStatus]): The code input.
                params (Optional[Dict[str, JsonValue]]): The params input.

            Returns:
                None
            """
            if params is None:
                params = {}
            if isinstance(code, EventType):
                msg, _ = Translator.get(code, params)
            else:
                msg = CommandHandlers._format_daemon_status(code, params)
            sys.stdout.write(f'{output_spacer.format(msg)}\n')
            sys.stdout.flush()

        configure_daemon_runtime_logging(sql_log_cb, tor_log_cb)

        if start_locked:
            try:
                run_managed_daemon(
                    pm,
                    password=password,
                    session_auth_password=session_auth_password,
                    start_locked=True,
                    status_callback=status_cb,
                    preparation=preparation,
                    chat_owner=chat_owner,
                )
            except InvalidDaemonPasswordError:
                msg, _ = Translator.get(EventType.INVALID_PASSWORD)
                print(output_spacer.format(msg))
                return 1
            except CorruptedDaemonStorageError:
                msg, _ = Translator.get(EventType.DB_CORRUPTED)
                print(
                    output_spacer.format(
                        f"{msg}\nYou need to run 'metor purge' or manually delete the storage.db."
                    )
                )
                return 1
            except PlaintextLockedDaemonError:
                print(
                    output_spacer.format(
                        'Plaintext profiles cannot be started in locked mode.'
                    )
                )
                return 1
            except ValueError as exc:
                print(
                    output_spacer.format(format_safe_local_runtime_error(exc)),
                    file=sys.stderr,
                )
                return 1
            return 0

        try:
            run_managed_daemon(
                pm,
                password=password,
                session_auth_password=session_auth_password,
                start_locked=False,
                status_callback=status_cb,
                preparation=preparation,
                chat_owner=chat_owner,
            )
        except InvalidDaemonPasswordError:
            msg, _ = Translator.get(EventType.INVALID_PASSWORD)
            print(output_spacer.format(msg))
            return 1
        except CorruptedDaemonStorageError:
            msg, _ = Translator.get(EventType.DB_CORRUPTED)
            print(
                output_spacer.format(
                    f"{msg}\nYou need to run 'metor purge' or manually delete the storage.db."
                )
            )
            return 1
        except ValueError as exc:
            print(
                output_spacer.format(format_safe_local_runtime_error(exc)),
                file=sys.stderr,
            )
            return 1
        except PlaintextLockedDaemonError:
            print(
                output_spacer.format(
                    'Plaintext profiles cannot be started in locked mode.'
                )
            )
            return 1
        return 0

    @staticmethod
    def handle_profile_security_migration(
        proxy: CliProxy,
        name: str,
        target_mode: ProfileSecurityMode,
    ) -> str:
        """
        Interactively migrates one local profile between encrypted and plaintext storage.

        Args:
            proxy (CliProxy): The active CLI proxy used for local headless routing.
            name (str): Target profile name.
            target_mode (ProfileSecurityMode): The requested storage mode.

        Returns:
            str: The formatted CLI outcome.
        """
        pm: ProfileManager = ProfileManager(name)
        if not pm.exists():
            return proxy.migrate_profile_security(name, target_mode)

        current_mode: ProfileSecurityMode = pm.get_security_mode()
        if current_mode is target_mode:
            return proxy.migrate_profile_security(name, target_mode)

        if target_mode is ProfileSecurityMode.PLAINTEXT:
            print(
                f'This will store the profile database and local keys in '
                f'{Theme.RED}plaintext at rest{Theme.RESET}.'
            )
            try:
                confirm: str = prompt_text("Type 'yes' to continue: ")
            except PromptAbortedError:
                return 'Security migration aborted.'
            if confirm.strip().lower() != 'yes':
                return 'Security migration aborted.'

        current_password: Optional[str] = None
        output_spacer = PromptOutputSpacer()
        if current_mode is ProfileSecurityMode.ENCRYPTED:
            try:
                current_password = prompt_hidden(
                    f'{Theme.GREEN}Enter Current Master Password: {Theme.RESET}'
                )
                output_spacer.mark_prompt()
            except PromptAbortedError:
                return 'Security migration aborted.'
            if not current_password:
                return output_spacer.format('Current master password cannot be empty.')

        new_password: Optional[str] = None
        if target_mode is ProfileSecurityMode.ENCRYPTED:
            try:
                new_password = prompt_hidden(
                    f'{Theme.GREEN}Enter New Master Password: {Theme.RESET}'
                )
                output_spacer.mark_prompt()
            except PromptAbortedError:
                return 'Security migration aborted.'
            if not new_password:
                return output_spacer.format('New master password cannot be empty.')

            try:
                confirm_password: str = prompt_hidden(
                    f'{Theme.GREEN}Confirm New Master Password: {Theme.RESET}'
                )
                output_spacer.mark_prompt()
            except PromptAbortedError:
                return 'Security migration aborted.'
            if new_password != confirm_password:
                return output_spacer.format('New master passwords do not match.')

        return output_spacer.format(
            proxy.migrate_profile_security(
                name,
                target_mode,
                current_password=current_password,
                new_password=new_password,
            )
        )

    @staticmethod
    def handle_chat(
        pm: ProfileManager | None,
        start_daemon_override: Optional[bool] = None,
        frontend_id: Optional[str] = None,
        list_uis: bool = False,
        loaded_frontend: Optional[LoadedFrontend] = None,
        device_config: Optional[str] = None,
        simulator: bool = False,
        debug: bool = False,
        initial_profile: str | None = None,
    ) -> int:
        """
        Validates daemon state and launches the interactive Chat UI.

        Args:
            pm (ProfileManager): The active profile configuration.
            start_daemon_override (Optional[bool]): Optional one-shot CLI override for local daemon autostart.
            frontend_id (Optional[str]): Explicit frontend selection.
            list_uis (bool): Whether to list installed frontend metadata only.
            loaded_frontend (Optional[LoadedFrontend]): Frontend already checked
                before profile and daemon initialization by the CLI entry point.

        Returns:
            int: Process exit status.
        """
        if list_uis:
            return CommandHandlers.handle_list_frontends()

        selected_frontend: str = (
            frontend_id
            or os.environ.get('METOR_UI')
            or (
                pm.config.get_str(SettingKey.DEFAULT_UI)
                if pm is not None
                else Settings.get_str(SettingKey.DEFAULT_UI, persist_defaults=False)
            )
        )
        if loaded_frontend is None:
            try:
                loaded_frontend = load_frontend(selected_frontend)
            except FrontendLaunchError as exc:
                sys.stderr.write(f'{exc}\n')
                return 2

        selected_name = pm.profile_name if pm is not None else initial_profile
        host = create_local_frontend_host(
            pm if pm is not None else selected_name, start_daemon_override
        )
        context = FrontendLaunchContext(
            profile=selected_name,
            host=host,
            start_daemon=start_daemon_override,
            device_config=device_config,
            simulator=simulator,
            debug=debug,
        )
        status = 0
        try:
            status = invoke_frontend(loaded_frontend, context)
        except FrontendLaunchError as exc:
            sys.stderr.write(f'{exc}\n')
            status = 2
        finally:
            try:
                host.close()
            except (OSError, RuntimeError):
                sys.stderr.write('Metor chat cleanup failed [owned-daemon].\n')
                if status == 0:
                    status = 1
        return status

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

        result = cleanup_local_runtime(force=force)

        if result.killed_processes > 0:
            print(
                'Cleanup completed. Managed processes were terminated and daemon state was cleared.'
            )
            return

        if result.cleared_runtime_state > 0:
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
                ProfileManager.purge_all_data()
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
            event = proxy.nuke_daemon_event()
            if (
                event is None
                or event.event_type is not EventType.SELF_DESTRUCT_INITIATED
            ):
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
