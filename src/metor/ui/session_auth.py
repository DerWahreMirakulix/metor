"""Shared UI helpers for prompting and building local daemon session-auth proofs."""

from typing import Optional

from metor.core.api import AuthRequiredEvent, InvalidPasswordEvent, IpcEvent
from metor.utils import build_session_auth_proof

# Local Package Imports
from metor.ui.prompt import prompt_hidden
from metor.ui.theme import Theme


def extract_session_auth_prompt(event: IpcEvent) -> Optional[tuple[str, str]]:
    """
    Extracts the daemon-issued challenge payload from one auth-gate event.

    Args:
        event (IpcEvent): The incoming IPC event.

    Returns:
        Optional[tuple[str, str]]: The challenge and salt, or None when unavailable.
    """
    if isinstance(event, (AuthRequiredEvent, InvalidPasswordEvent)):
        if event.challenge is not None and event.salt is not None:
            return event.challenge, event.salt

    return None


def prompt_session_auth_proof(
    prompt: str,
    challenge: str,
    salt: str,
) -> Optional[str]:
    """
    Prompts for the master password and converts it into one session-auth proof.

    Args:
        prompt (str): The prompt text shown to the user.
        challenge (str): The daemon-issued challenge.
        salt (str): The daemon-issued salt.

    Returns:
        Optional[str]: The derived proof, or None when the password is empty.
    """
    password: str = prompt_hidden(f'{Theme.GREEN}{prompt}{Theme.RESET}')
    if not password:
        return None

    return build_session_auth_proof(password, challenge, salt)
