"""Shared UI helpers for prompting and building local daemon session-auth proofs."""

from typing import Optional

from metor.client.auth import extract_session_auth_prompt
from metor.data import ProfileManager
from metor.utils import build_session_auth_proof

# Local Package Imports
from metor.ui.prompt import prompt_hidden_optional
from metor.ui.theme import Theme

__all__ = [
    'extract_session_auth_prompt',
    'get_session_auth_prompt',
    'prompt_session_auth_proof',
]


def prompt_session_auth_proof(
    prompt: str,
    challenge: str,
    salt: str,
) -> Optional[str]:
    """
    Prompts for one local auth password and converts it into one session-auth proof.

    Args:
        prompt (str): The prompt text shown to the user.
        challenge (str): The daemon-issued challenge.
        salt (str): The daemon-issued salt.

    Returns:
        Optional[str]: The derived proof, or None when the password is empty.
    """
    password: Optional[str] = prompt_hidden_optional(
        f'{Theme.GREEN}{prompt}{Theme.RESET}'
    )
    if password is None:
        return None

    return build_session_auth_proof(password, challenge, salt)


def get_session_auth_prompt(pm: ProfileManager) -> str:
    """
    Resolves the user-facing prompt label for per-session daemon auth.

    Args:
        pm (ProfileManager): The active profile manager.

    Returns:
        str: The prompt text without terminal styling.
    """
    if pm.uses_encrypted_storage():
        return 'Enter Master Password: '
    return 'Enter Session Auth Password: '
