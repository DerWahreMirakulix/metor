"""Message-specific CLI dispatch mixin."""

from typing import List, Optional, Protocol

from metor.ui import Help
from metor.ui.cli.proxy import CliProxy


class _MessagesDispatcherProtocol(Protocol):
    """Structural type for the dispatcher attributes used by the messages mixin."""

    _extra: List[str]
    _help: type[Help]
    _proxy: CliProxy
    _exit_code: int

    def _print_usage(self, cmd: str, sub: Optional[str] = None) -> None:
        """Prints command usage help and flags a nonzero exit code."""
        ...

    def _emit(self, text: str) -> None:
        """Prints one proxy result and flags a nonzero exit on rendered errors."""
        ...


    def _collect_command_args(
        self,
        sub: Optional[str],
        extra: List[str],
        reserved_subcommands: tuple[str, ...],
    ) -> List[str]:
        """Collects positional command arguments, excluding reserved subcommand tokens."""
        ...

    def _parse_optional_limit(self, limit_raw: Optional[str]) -> Optional[int]:
        """Parses an optional integer limit token and returns None for invalid input."""
        ...


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
                self._print_usage('messages')
                return

            target: Optional[str] = clean_args[0] if clean_args else None
            self._emit(self._proxy.clear_messages(target, non_contacts_only))
            return

        if non_contacts_only:
            self._print_usage('messages')
            return

        message_args: List[str] = self._collect_command_args(
            sub,
            clean_args,
            ('show', 'clear'),
        )
        if not message_args or len(message_args) > 2:
            self._print_usage('messages')
            return

        limit: Optional[int] = None
        if len(message_args) == 2:
            limit = self._parse_optional_limit(message_args[1])
            if limit is None:
                self._print_usage('messages')
                return

        self._emit(self._proxy.get_messages(message_args[0], limit))
