"""CLI dispatcher facade coordinating modular command routing helpers."""

import argparse
from typing import List, Optional, Tuple

from metor.core.api import ProfileEntry, ProfilesDataEvent
from metor.data.profile import (
    ProfileManager,
    ProfileOperationResult,
    ProfileOperationType,
    ProfileSecurityMode,
    ProfileSummary,
)
from metor.ui import Help, UIPresenter

# Local Package Imports
from metor.ui.cli.dispatcher.history import HistoryDispatchMixin
from metor.ui.cli.dispatcher.messages import MessagesDispatchMixin
from metor.ui.cli.handlers import CommandHandlers
from metor.ui.cli.proxy import CliProxy


class CliDispatcher(MessagesDispatchMixin, HistoryDispatchMixin):
    """Routes parsed CLI arguments to the corresponding application logic."""

    _help = Help

    @staticmethod
    def _collect_command_args(
        sub: Optional[str],
        extra: List[str],
        reserved_subcommands: Tuple[str, ...],
    ) -> List[str]:
        """
        Collects positional arguments while supporting shorthand target invocation.

        Args:
            sub (Optional[str]): Parsed subcommand token.
            extra (List[str]): Additional raw positional arguments.
            reserved_subcommands (Tuple[str, ...]): Reserved subcommand keywords.

        Returns:
            List[str]: Ordered positional arguments for the command action.
        """
        args: List[str] = list(extra)
        if sub and sub not in reserved_subcommands:
            args.insert(0, sub)
        return args

    @staticmethod
    def _parse_optional_limit(limit_raw: Optional[str]) -> Optional[int]:
        """
        Parses a decimal limit argument.

        Args:
            limit_raw (Optional[str]): Raw CLI token.

        Returns:
            Optional[int]: Parsed limit, or None if absent or invalid.
        """
        if limit_raw is None:
            return None
        if not limit_raw.isdigit():
            return None
        return int(limit_raw)

    @staticmethod
    def _format_profile_result(result: ProfileOperationResult) -> str:
        """
        Renders a local profile operation result directly for the CLI.

        Args:
            result (ProfileOperationResult): The local profile operation outcome.

        Returns:
            str: The user-facing CLI message.
        """
        params = result.params

        if result.operation_type is ProfileOperationType.INVALID_NAME:
            return 'Invalid profile name.'
        if result.operation_type is ProfileOperationType.DEFAULT_SET:
            return f"Default profile permanently set to '{params['profile']}'."
        if result.operation_type is ProfileOperationType.REMOTE_PORT_REQUIRED:
            return 'A remote profile requires a static port (--port <int>).'
        if (
            result.operation_type
            is ProfileOperationType.PASSWORDLESS_REMOTE_NOT_ALLOWED
        ):
            return 'Remote profiles cannot be created without password protection.'
        if result.operation_type is ProfileOperationType.PROFILE_EXISTS:
            return f"Profile '{params['profile']}' already exists."
        if result.operation_type is ProfileOperationType.PROFILE_CREATED:
            if params.get('security_mode') == ProfileSecurityMode.PLAINTEXT.value:
                return (
                    f"Profile '{params['profile']}' successfully created without "
                    'password protection.'
                )
            return f"Profile '{params['profile']}' successfully created."
        if result.operation_type is ProfileOperationType.PROFILE_CREATED_WITH_PORT:
            storage_suffix: str = ''
            if params.get('security_mode') == ProfileSecurityMode.PLAINTEXT.value:
                storage_suffix = ' without password protection'
            return (
                f"{params['remote_tag']}profile '{params['profile']}' successfully "
                f'created{storage_suffix} (Port {params["port"]}).'
            )
        if (
            result.operation_type
            is ProfileOperationType.SECURITY_MIGRATION_REMOTE_NOT_ALLOWED
        ):
            return 'Remote profiles cannot migrate local storage security mode.'
        if result.operation_type is ProfileOperationType.CANNOT_MIGRATE_RUNNING:
            return (
                f"Cannot migrate security mode for '{params['profile']}' while its "
                'daemon is running.'
            )
        if result.operation_type is ProfileOperationType.SECURITY_MODE_UNCHANGED:
            return (
                f"Profile '{params['profile']}' is already using "
                f'{params["security_mode"]} storage.'
            )
        if result.operation_type is ProfileOperationType.SECURITY_MODE_MIGRATED:
            return (
                f"Profile '{params['profile']}' successfully migrated to "
                f'{params["security_mode"]} storage.'
            )
        if result.operation_type is ProfileOperationType.SECURITY_MIGRATION_FAILED:
            reason: str = str(params.get('reason') or 'Security migration failed.')
            return reason
        if result.operation_type is ProfileOperationType.PROFILE_NOT_FOUND:
            return f"Profile '{params['profile']}' does not exist."
        if result.operation_type is ProfileOperationType.CANNOT_REMOVE_ACTIVE:
            return 'Cannot remove active profile! Switch to another profile first.'
        if result.operation_type is ProfileOperationType.CANNOT_REMOVE_DEFAULT:
            return 'Cannot remove default profile! Change default first.'
        if result.operation_type is ProfileOperationType.CANNOT_REMOVE_RUNNING:
            return f"Cannot remove profile '{params['profile']}' while its daemon is running!"
        if result.operation_type is ProfileOperationType.PROFILE_REMOVED:
            return f"Profile '{params['profile']}' successfully removed."
        if result.operation_type is ProfileOperationType.CANNOT_RENAME_RUNNING:
            return f"Cannot rename profile '{params['old_profile']}' while its daemon is running!"
        if result.operation_type is ProfileOperationType.PROFILE_RENAMED:
            return (
                f"Profile '{params['old_profile']}' successfully renamed to "
                f"'{params['new_profile']}'."
            )
        if result.operation_type is ProfileOperationType.CANNOT_CLEAR_RUNNING_DB:
            return f"Cannot clear database for '{params['profile']}' while daemon is running."
        if result.operation_type is ProfileOperationType.DATABASE_NOT_FOUND:
            return f"No database found for profile '{params['profile']}'."
        if result.operation_type is ProfileOperationType.DATABASE_CLEARED:
            return f"Database for profile '{params['profile']}' successfully cleared."
        if result.operation_type is ProfileOperationType.DATABASE_CLEAR_FAILED:
            return 'Error clearing database.'

        return 'Unknown profile operation result.'

    def __init__(
        self,
        args: argparse.Namespace,
        extra: List[str],
        pm: ProfileManager,
    ) -> None:
        """
        Initializes the dispatcher with the parsed arguments and active profile.

        Args:
            args (argparse.Namespace): The parsed CLI arguments.
            extra (List[str]): Extra unparsed arguments.
            pm (ProfileManager): The active profile configuration.

        Returns:
            None
        """
        self._args: argparse.Namespace = args
        self._extra: List[str] = extra
        self._pm: ProfileManager = pm
        self._proxy: CliProxy = CliProxy(pm)

    def dispatch(self) -> None:
        """
        Evaluates the command string and executes the matching subsystem or proxy call.

        Args:
            None

        Returns:
            None
        """
        cmd: str = self._args.command
        sub: Optional[str] = self._args.subcommand

        is_help_request: bool = False
        if cmd in ('-h', '--help'):
            is_help_request = True
            cmd = 'help'
        elif sub in ('-h', '--help'):
            is_help_request = True
        elif '-h' in self._extra or '--help' in self._extra:
            is_help_request = True

        if is_help_request:
            if cmd and cmd not in ('help', 'quickstart', '-h', '--help'):
                print(self._help.show_command_help(cmd, sub))
            else:
                print(self._help.show_main_help())
            return

        if cmd == 'quickstart':
            print(self._help.show_quick_start())

        elif cmd == 'help':
            print(self._help.show_main_help())

        elif cmd == 'daemon':
            if sub or self._extra:
                print(self._help.show_command_help(cmd))
            else:
                CommandHandlers.handle_daemon(
                    self._pm,
                    start_locked=getattr(self._args, 'locked', False),
                )

        elif cmd == 'unlock':
            if sub or self._extra:
                print(self._help.show_command_help(cmd))
            else:
                print(self._proxy.unlock_daemon())

        elif cmd == 'settings':
            if sub == 'set' and len(self._extra) >= 2:
                print(self._proxy.handle_settings_set(self._extra[0], self._extra[1]))
            elif sub == 'get' and len(self._extra) >= 1:
                print(self._proxy.handle_settings_get(self._extra[0]))
            else:
                print(self._help.show_command_help(cmd))

        elif cmd == 'config':
            if sub == 'set' and len(self._extra) >= 2:
                print(self._proxy.handle_config_set(self._extra[0], self._extra[1]))
            elif sub == 'get' and len(self._extra) >= 1:
                print(self._proxy.handle_config_get(self._extra[0]))
            elif sub == 'sync':
                print(self._proxy.handle_config_sync())
            else:
                print(self._help.show_command_help(cmd))

        elif cmd == 'chat':
            CommandHandlers.handle_chat(self._pm)

        elif cmd == 'cleanup':
            cleanup_tokens: List[str] = []
            if sub:
                cleanup_tokens.append(sub)
            cleanup_tokens.extend(self._extra)

            invalid_tokens: List[str] = [
                token for token in cleanup_tokens if token != '--force'
            ]
            if invalid_tokens:
                print(self._help.show_command_help(cmd))
            else:
                CommandHandlers.handle_cleanup(force='--force' in cleanup_tokens)

        elif cmd == 'purge':
            is_nuke_remote: bool = (
                '--nuke-remote' in self._extra or sub == '--nuke-remote'
            )
            CommandHandlers.handle_purge(is_nuke_remote)

        elif cmd == 'send':
            if not sub or not self._extra:
                print(self._help.show_command_help(cmd))
            else:
                print(self._proxy.send_drop(sub, ' '.join(self._extra)))

        elif cmd == 'inbox':
            print(self._proxy.handle_inbox(sub))

        elif cmd == 'messages':
            self._dispatch_messages(sub)

        elif cmd == 'history':
            self._dispatch_history(sub)

        elif cmd == 'address':
            if sub in (None, 'show', 'generate'):
                print(self._proxy.get_address(generate=(sub == 'generate')))
            else:
                print(self._help.show_command_help(cmd))

        elif cmd == 'contacts':
            if sub == 'add':
                if len(self._extra) < 1:
                    print(self._help.show_command_help(cmd))
                else:
                    onion: Optional[str] = (
                        self._extra[1] if len(self._extra) > 1 else None
                    )
                    print(self._proxy.contacts_add(self._extra[0], onion))
            elif sub in ('rm', 'remove'):
                if len(self._extra) < 1:
                    print(self._help.show_command_help(cmd))
                else:
                    print(self._proxy.contacts_rm(self._extra[0]))
            elif sub == 'rename':
                if len(self._extra) < 2:
                    print(self._help.show_command_help(cmd))
                else:
                    print(self._proxy.contacts_rename(self._extra[0], self._extra[1]))
            elif sub == 'clear':
                print(self._proxy.contacts_clear())
            elif sub in ('list', None):
                print(self._proxy.contacts_list())
            else:
                print(self._help.show_command_help(cmd))

        elif cmd == 'profiles':
            if sub == 'add':
                if len(self._extra) < 1:
                    print(self._help.show_command_help(cmd))
                else:
                    security_mode: ProfileSecurityMode = (
                        ProfileSecurityMode.PLAINTEXT
                        if getattr(self._args, 'no_password', False)
                        else ProfileSecurityMode.ENCRYPTED
                    )
                    result: ProfileOperationResult = ProfileManager.add_profile_folder(
                        self._extra[0],
                        is_remote=getattr(self._args, 'remote', False),
                        port=getattr(self._args, 'port', None),
                        security_mode=security_mode,
                    )
                    print(self._format_profile_result(result))
            elif sub == 'migrate':
                profile_args: List[str] = list(self._extra)
                target_mode_value: Optional[str] = None

                if '--to' in profile_args:
                    to_index: int = profile_args.index('--to')
                    if to_index + 1 < len(profile_args):
                        target_mode_value = profile_args[to_index + 1]
                        del profile_args[to_index : to_index + 2]

                if len(profile_args) != 1 or target_mode_value is None:
                    print(self._help.show_command_help(cmd, sub))
                else:
                    try:
                        target_mode = ProfileSecurityMode(
                            target_mode_value.strip().lower()
                        )
                    except ValueError:
                        print(self._help.show_command_help(cmd, sub))
                        return

                    result = CommandHandlers.handle_profile_security_migration(
                        profile_args[0],
                        target_mode,
                    )
                    print(self._format_profile_result(result))
            elif sub in ('rm', 'remove'):
                if len(self._extra) < 1:
                    print(self._help.show_command_help(cmd))
                else:
                    target_profile: str = self._extra[0]
                    is_nuke_remote = '--nuke-remote' in self._extra

                    if is_nuke_remote:
                        remotes = (
                            [target_profile]
                            if ProfileManager(target_profile).is_remote()
                            else []
                        )
                        if remotes and not CommandHandlers._nuke_remote_profiles(
                            remotes
                        ):
                            print('Profile removal aborted.')
                            return

                    result = ProfileManager.remove_profile_folder(
                        target_profile,
                        self._pm.profile_name,
                    )
                    print(self._format_profile_result(result))
            elif sub == 'rename':
                if len(self._extra) < 2:
                    print(self._help.show_command_help(cmd))
                else:
                    result = ProfileManager.rename_profile_folder(
                        self._extra[0],
                        self._extra[1],
                    )
                    print(self._format_profile_result(result))
            elif sub == 'set-default':
                if len(self._extra) < 1:
                    print(self._help.show_command_help(cmd))
                else:
                    result = ProfileManager.set_default_profile(self._extra[0])
                    print(self._format_profile_result(result))
            elif sub == 'clear':
                if len(self._extra) < 1:
                    print(self._help.show_command_help(cmd))
                else:
                    target_pm: ProfileManager = ProfileManager(self._extra[0])
                    target_proxy: CliProxy = CliProxy(target_pm)
                    print(target_proxy.clear_profile_db())
            elif sub in ('list', None):
                summaries: List[ProfileSummary] = ProfileManager.get_profile_summaries(
                    self._pm.profile_name
                )
                profiles_event: ProfilesDataEvent = ProfilesDataEvent(
                    profiles=[
                        ProfileEntry(
                            name=summary.name,
                            is_active=summary.is_active,
                            is_remote=summary.is_remote,
                            port=summary.port,
                        )
                        for summary in summaries
                    ]
                )
                print(UIPresenter.format_profiles(profiles_event))
            else:
                print(self._help.show_command_help(cmd))

        else:
            print("Unknown command. Use 'metor help' to see available commands.")
