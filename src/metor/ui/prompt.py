"""
Module containing centralized UI prompt helpers.
Normalizes interactive prompt aborts so Ctrl-C and EOF do not leak raw stack traces.
"""

import getpass
import sys


class PromptAbortedError(Exception):
    """Raised when an interactive prompt is aborted by the user."""


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
        return getpass.getpass(prompt)
    except (EOFError, KeyboardInterrupt) as exc:
        _emit_prompt_abort_newline()
        raise PromptAbortedError() from exc


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
