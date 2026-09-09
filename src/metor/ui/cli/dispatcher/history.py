"""History-specific CLI dispatch mixin."""

from typing import List, Optional, Protocol

from metor.ui import Help
from metor.ui.cli.proxy import CliProxy


class _HistoryDispatcherProtocol(Protocol):
    """Structural type for the dispatcher attributes used by the history mixin."""

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

    def _parse_optional_limit(self, limit_raw: Optional[str]) -> Optional[int]:
        """Parses an optional integer limit token and returns None for invalid input."""
        ...


class HistoryDispatchMixin:
    """Adds `history` command routing to the CLI dispatcher."""

    def _dispatch_history(
        self: _HistoryDispatcherProtocol,
        sub: Optional[str],
    ) -> None:
        """
        Validates and routes the `history` command.

        Args:
            sub (Optional[str]): Parsed subcommand token.

        Returns:
            None
        """
        tokens: List[str] = []
        if sub:
            tokens.append(sub)
        tokens.extend(self._extra)

        raw_requested: bool = '--raw' in tokens
        clean_tokens: List[str] = [token for token in tokens if token != '--raw']

        if clean_tokens and clean_tokens[0] == 'clear':
            clear_args: List[str] = clean_tokens[1:]
            if raw_requested or len(clear_args) > 1:
                self._print_usage('history')
                return

            clear_target: Optional[str] = clear_args[0] if clear_args else None
            self._emit(self._proxy.clear_history(clear_target))
            return

        history_args: List[str]
        if clean_tokens and clean_tokens[0] == 'show':
            history_args = clean_tokens[1:]
        else:
            history_args = clean_tokens

        if len(history_args) > 2:
            self._print_usage('history')
            return

        target: Optional[str] = history_args[0] if history_args else None
        limit: Optional[int] = None
        if len(history_args) == 2:
            limit = self._parse_optional_limit(history_args[1])
            if limit is None:
                self._print_usage('history')
                return

        self._emit(self._proxy.get_history(target, limit, raw=raw_requested))
