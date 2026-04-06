"""Message-specific CLI dispatch mixin."""

from typing import List, Optional, Protocol

from metor.ui import Help
from metor.ui.cli.proxy import CliProxy


class _MessagesDispatcherProtocol(Protocol):
    """Structural type for the dispatcher attributes used by the messages mixin."""

    _extra: List[str]
    _help: type[Help]
    _proxy: CliProxy

    def _collect_command_args(
        self,
        sub: Optional[str],
        extra: List[str],
        reserved_subcommands: tuple[str, ...],
    ) -> List[str]: ...

    def _parse_optional_limit(self, limit_raw: Optional[str]) -> Optional[int]: ...


class MessagesDispatchMixin:
    """Adds `messages` command routing to the CLI dispatcher."""

    def _dispatch_messages(
        self: _MessagesDispatcherProtocol,
        sub: Optional[str],
    ) -> None:
        """
        Validates and routes the `messages` command.

        Args:
            sub (Optional[str]): Parsed subcommand token.

        Returns:
            None
        """
        non_contacts_only: bool = '--non-contacts' in self._extra
        clean_args: List[str] = [x for x in self._extra if x != '--non-contacts']

        if sub == 'clear':
            if len(clean_args) > 1:
                print(self._help.show_command_help('messages'))
                return

            target: Optional[str] = clean_args[0] if clean_args else None
            print(self._proxy.clear_messages(target, non_contacts_only))
            return

        if non_contacts_only:
            print(self._help.show_command_help('messages'))
            return

        message_args: List[str] = self._collect_command_args(
            sub,
            clean_args,
            ('show', 'clear'),
        )
        if not message_args or len(message_args) > 2:
            print(self._help.show_command_help('messages'))
            return

        limit: Optional[int] = None
        if len(message_args) == 2:
            limit = self._parse_optional_limit(message_args[1])
            if limit is None:
                print(self._help.show_command_help('messages'))
                return

        print(self._proxy.get_messages(message_args[0], limit))
