"""Profile-specific CLI dispatch mixin."""

import argparse
from typing import List, Optional, Protocol

from metor.data.profile import ProfileManager, ProfileSecurityMode
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
                print(self._help.show_command_help('profiles'))
                return

            security_mode: ProfileSecurityMode = (
                ProfileSecurityMode.PLAINTEXT
                if getattr(self._args, 'plaintext', False)
                else ProfileSecurityMode.ENCRYPTED
            )
            print(
                self._proxy.add_profile(
                    self._extra[0],
                    is_remote=getattr(self._args, 'remote', False),
                    port=getattr(self._args, 'port', None),
                    security_mode=security_mode,
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
                print(self._help.show_command_help('profiles', sub))
                return

            try:
                target_mode = ProfileSecurityMode(target_mode_value.strip().lower())
            except ValueError:
                print(self._help.show_command_help('profiles', sub))
                return

            print(
                CommandHandlers.handle_profile_security_migration(
                    self._proxy,
                    profile_args[0],
                    target_mode,
                )
            )
            return

        if sub in ('rm', 'remove'):
            if len(self._extra) < 1:
                print(self._help.show_command_help('profiles'))
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
                    return

            print(
                self._proxy.remove_profile(
                    target_profile,
                    active_profile=self._pm.profile_name,
                )
            )
            return

        if sub == 'rename':
            if len(self._extra) < 2:
                print(self._help.show_command_help('profiles'))
                return

            print(self._proxy.rename_profile(self._extra[0], self._extra[1]))
            return

        if sub == 'set-default':
            if len(self._extra) < 1:
                print(self._help.show_command_help('profiles'))
                return

            print(self._proxy.set_default_profile(self._extra[0]))
            return

        if sub == 'clear':
            if len(self._extra) < 1:
                print(self._help.show_command_help('profiles'))
                return

            target_proxy = CliProxy(ProfileManager(self._extra[0]))
            print(target_proxy.clear_profile_db())
            return

        if sub in ('list', None):
            print(self._proxy.list_profiles(self._pm.profile_name))
            return

        print(self._help.show_command_help('profiles'))
