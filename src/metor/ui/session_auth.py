"""Shared UI helpers for prompting and building local daemon session-auth proofs."""

from typing import Optional

from metor.utils import build_session_auth_proof

# Local Package Imports
from metor.ui.prompt import prompt_hidden
from metor.ui.theme import Theme


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
