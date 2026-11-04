"""
Module containing centralized UI prompt helpers.
Normalizes interactive prompt aborts so Ctrl-C and EOF do not leak raw stack traces.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import getpass
import os
import sys
from typing import Iterator

if os.name == 'posix':
    import termios


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


@contextmanager
def _canonical_prompt_input() -> Iterator[None]:
    """Make EOF work in a hidden prompt even when chat editing already uses cbreak.

    getpass owns echo suppression and credential collection. This context owns
    only line discipline, restoring the exact prior terminal state afterward.
    """
    if os.name != 'posix' or not sys.stdin.isatty():
        yield
        return
    fd = sys.stdin.fileno()
    get_attributes = getattr(termios, 'tcgetattr')
    set_attributes = getattr(termios, 'tcsetattr')
    immediate = getattr(termios, 'TCSANOW')
    previous = get_attributes(fd)
    canonical = list(previous)
    canonical[0] &= ~(getattr(termios, 'INLCR') | getattr(termios, 'IGNCR'))
    canonical[0] |= getattr(termios, 'ICRNL')
    canonical[3] |= getattr(termios, 'ICANON')
    set_attributes(fd, immediate, canonical)
    try:
        yield
    finally:
        set_attributes(fd, immediate, previous)


def prompt_hidden(prompt: str) -> str:
    """
    Requests a hidden terminal input value such as a password.

    Args:
        prompt (str): The rendered prompt text.

    Raises:
        PromptAbortedError: If the prompt is aborted via Ctrl-C or EOF.

    Returns:
        str: The entered text, which may be empty.
    """
    try:
        with _canonical_prompt_input():
            return getpass.getpass(prompt)
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
        return input(prompt)
    except (EOFError, KeyboardInterrupt) as exc:
        _emit_prompt_abort_newline()
        raise PromptAbortedError() from exc
