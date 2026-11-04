"""
Module containing centralized UI prompt helpers.
Normalizes interactive prompt aborts so Ctrl-C and EOF do not leak raw stack traces.
"""

from dataclasses import dataclass
import codecs
import getpass
import io
import sys

from metor.utils import Constants


class PromptAbortedError(Exception):
    """Raised when an interactive prompt is aborted by the user."""


@dataclass
class PromptOutputSpacer:
    """Tracks whether the next visible output should be separated from a prompt."""

    pending: bool = False

    def mark_prompt(self) -> None:
        """
        Marks that a prompt just completed and the next output should be separated.

        Args:
            None

        Returns:
            None
        """
        self.pending = True

    def format(self, rendered: str) -> str:
        """
        Prefixes exactly one blank line before the next non-empty output.

        Args:
            rendered (str): The rendered output text.

        Returns:
            str: The normalized output.
        """
        if not rendered:
            return rendered

        if not self.pending:
            return rendered

        self.pending = False
        return f'\n{rendered}'


def _emit_prompt_abort_newline() -> None:
    """
    Moves the terminal cursor to a clean new line after an aborted prompt.

    Args:
        None

    Returns:
        None
    """
    sys.stderr.write('\n')
    sys.stderr.flush()


def _prepare_prompt_input() -> None:
    """Select UTF-8 before a redirected text stream can prefetch later secrets."""
    if sys.stdin is None:
        raise EOFError
    if not isinstance(sys.stdin, io.TextIOWrapper):
        return
    try:
        if sys.stdin.isatty():
            return
        if (
            codecs.lookup(sys.stdin.encoding).name != 'utf-8'
            or sys.stdin.errors != 'strict'
        ):
            sys.stdin.reconfigure(encoding='utf-8', errors='strict')
    except (OSError, ValueError):
        # Reconfiguring after an external text read can discard or reinterpret
        # prefetched data. Fail rather than authenticate a different password.
        sys.stderr.write('Redirected input could not be configured as UTF-8.\n')
        sys.stderr.flush()
        raise PromptAbortedError() from None


def prompt_hidden(prompt: str) -> str:
    """
    Requests a hidden terminal password or one bounded redirected stdin line.

    Args:
        prompt (str): The rendered prompt text.

    Raises:
        PromptAbortedError: If the prompt is aborted via Ctrl-C or EOF.

    Returns:
        str: The entered text, which may be empty.
    """
    try:
        _prepare_prompt_input()
        if sys.stdin.isatty():
            return getpass.getpass(prompt)
        # Windows getpass reads the console even when stdin is a pipe. Select
        # the explicit input stream here and never echo its contents.
        sys.stderr.write(prompt)
        sys.stderr.flush()
        line = sys.stdin.readline(Constants.CLI_PIPE_SECRET_MAX_BYTES + 2)
        if not line:
            raise EOFError
        secret = line.removesuffix('\n').removesuffix('\r')
        oversized = len(secret.encode('utf-8')) > Constants.CLI_PIPE_SECRET_MAX_BYTES
        if oversized:
            sys.stderr.write('\nPassword input exceeds the supported limit.\n')
            # Abort the operation: no truncated prefix or unread suffix may
            # become a credential for this or a subsequent confirmation prompt.
            raise PromptAbortedError()
        sys.stderr.write('\n')
        sys.stderr.flush()
        return secret
    except UnicodeError:
        sys.stderr.write('\nPassword input is not valid UTF-8.\n')
        raise PromptAbortedError() from None
    except (EOFError, KeyboardInterrupt) as exc:
        _emit_prompt_abort_newline()
        raise PromptAbortedError() from exc


def prompt_hidden_optional(prompt: str) -> str | None:
    """
    Requests a hidden terminal input value and normalizes empty input to None.

    Args:
        prompt (str): The rendered prompt text.

    Raises:
        PromptAbortedError: If the prompt is aborted via Ctrl-C or EOF.

    Returns:
        str | None: The entered text, or None when the input is empty.
    """
    value: str = prompt_hidden(prompt)
    if not value:
        return None
    return value


def prompt_text(prompt: str) -> str:
    """
    Requests a visible terminal input value.

    Args:
        prompt (str): The rendered prompt text.

    Raises:
        PromptAbortedError: If the prompt is aborted via Ctrl-C or EOF.

    Returns:
        str: The entered text, which may be empty.
    """
    try:
        _prepare_prompt_input()
        return input(prompt)
    except UnicodeError:
        sys.stderr.write('\nInput is not valid UTF-8.\n')
        raise PromptAbortedError() from None
    except (EOFError, KeyboardInterrupt) as exc:
        _emit_prompt_abort_newline()
        raise PromptAbortedError() from exc
