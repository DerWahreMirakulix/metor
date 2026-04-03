"""History-specific CLI dispatch mixin."""

from typing import Any, List, Optional, Protocol


class _HistoryDispatcherProtocol(Protocol):
    """Structural type for the dispatcher attributes used by the history mixin."""

    _extra: List[str]
    _help: Any
    _proxy: Any

    def _parse_optional_limit(self, limit_raw: Optional[str]) -> Optional[int]: ...


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
                print(self._help.show_command_help('history'))
                return

            clear_target: Optional[str] = clear_args[0] if clear_args else None
            print(self._proxy.clear_history(clear_target))
            return

        history_args: List[str]
        if clean_tokens and clean_tokens[0] == 'show':
            history_args = clean_tokens[1:]
        else:
            history_args = clean_tokens

        if len(history_args) > 2:
            print(self._help.show_command_help('history'))
            return

        target: Optional[str] = history_args[0] if history_args else None
        limit: Optional[int] = None
        if len(history_args) == 2:
            limit = self._parse_optional_limit(history_args[1])
            if limit is None:
                print(self._help.show_command_help('history'))
                return

        print(self._proxy.get_history(target, limit, raw=raw_requested))
