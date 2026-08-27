"""Profile-specific CLI dispatch mixin."""

import argparse
from typing import List, Optional, Protocol

from metor.data import ProfileManager, ProfileSecurityMode
from metor.ui import Help
from metor.ui.cli.handlers import CommandHandlers
from metor.ui.cli.proxy import CliProxy


class _ProfilesDispatcherProtocol(Protocol):
    """Structural type for the dispatcher attributes used by the profiles mixin."""

    _args: argparse.Namespace
    _extra: List[str]
    _help: type[Help]
    _pm: ProfileManager
    _proxy: CliProxy
    _exit_code: int

    def _print_usage(self, cmd: str, sub: Optional[str] = None) -> None:
        """Prints command usage help and flags a nonzero exit code."""
        ...

    def _emit(self, text: str) -> None:
        """Prints one proxy result and flags a nonzero exit on rendered errors."""
        ...


class ProfilesDispatchMixin:
    """Adds `profiles` command routing to the CLI dispatcher."""

    def _dispatch_profiles(
        self: _ProfilesDispatcherProtocol, sub: Optional[str]
    ) -> None:
        """
        Validates and routes the `profiles` command.

        Args:
            sub (Optional[str]): Parsed subcommand token.

        Returns:
            None
        """
        if sub == 'add':
            if len(self._extra) < 1:
                self._print_usage('profiles')
                return

            security_mode: ProfileSecurityMode = (
                ProfileSecurityMode.PLAINTEXT
                if getattr(self._args, 'plaintext', False)
                else ProfileSecurityMode.ENCRYPTED
            )
            master_password: Optional[str] = None
            if security_mode is ProfileSecurityMode.ENCRYPTED and not getattr(
                self._args, 'remote', False
            ):
                import getpass

                master_password = getpass.getpass('Enter new master password: ')
                confirm_password = getpass.getpass('Confirm master password: ')
                if not master_password:
                    print('Error: master password must not be empty.')
                    return
                if master_password != confirm_password:
                    print('Error: passwords do not match. Profile not created.')
                    return
            self._emit(
                self._proxy.add_profile(
                    self._extra[0],
                    is_remote=getattr(self._args, 'remote', False),
                    port=getattr(self._args, 'port', None),
                    security_mode=security_mode,
                    master_password=master_password,
                )
            )
            return

        if sub == 'migrate':
            profile_args: List[str] = list(self._extra)
            target_mode_value: Optional[str] = None

            if '--to' in profile_args:
                to_index: int = profile_args.index('--to')
                if to_index + 1 < len(profile_args):
                    target_mode_value = profile_args[to_index + 1]
                    del profile_args[to_index : to_index + 2]

            if len(profile_args) != 1 or target_mode_value is None:
                self._print_usage('profiles', sub)
                return

            try:
                target_mode = ProfileSecurityMode(target_mode_value.strip().lower())
            except ValueError:
                self._print_usage('profiles', sub)
                return

            self._emit(
                CommandHandlers.handle_profile_security_migration(
                    self._proxy,
                    profile_args[0],
                    target_mode,
                )
            )
            return

        if sub in ('rm', 'remove'):
            if len(self._extra) < 1:
                self._print_usage('profiles')
                return

            target_profile: str = self._extra[0]
            is_nuke_remote: bool = '--nuke-remote' in self._extra

            if is_nuke_remote:
                remotes = (
                    [target_profile]
                    if ProfileManager(target_profile).is_remote()
                    else []
                )
                if remotes and not CommandHandlers._nuke_remote_profiles(remotes):
                    print('Profile removal aborted.')
                    self._exit_code = 1
                    return

            self._emit(
                self._proxy.remove_profile(
                    target_profile,
                    active_profile=self._pm.profile_name,
                )
            )
            return

        if sub == 'rename':
            if len(self._extra) < 2:
                self._print_usage('profiles')
                return

            self._emit(self._proxy.rename_profile(self._extra[0], self._extra[1]))
            return

        if sub == 'set-default':
            if len(self._extra) < 1:
                self._print_usage('profiles')
                return

            self._emit(self._proxy.set_default_profile(self._extra[0]))
            return

        if sub == 'clear':
            if len(self._extra) < 1:
                self._print_usage('profiles')
                return

            target_proxy = CliProxy(ProfileManager(self._extra[0]))
            self._emit(target_proxy.clear_profile_db())
            return

        if sub in ('list', None):
            self._emit(self._proxy.list_profiles(self._pm.profile_name))
            return

        self._print_usage('profiles')
