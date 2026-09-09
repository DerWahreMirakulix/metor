"""Public facade for the terminal frontend."""

from metor.data import (
    TERMINAL_UI_SETTINGS,
    get_registered_ui_settings,
    register_ui_settings,
)
from metor.ui.terminal.help import CommandDef, Help, SubCommandDef
from metor.ui.terminal.models import AliasPolicy, StatusTone, TranslationDef
from metor.ui.terminal.presenter import UIPresenter
from metor.ui.terminal.prompt import (
    PromptAbortedError,
    PromptOutputSpacer,
    prompt_hidden,
    prompt_hidden_optional,
    prompt_text,
)
from metor.ui.terminal.session_auth import (
    extract_session_auth_prompt,
    get_session_auth_prompt,
    prompt_session_auth_proof,
)
from metor.ui.terminal.theme import Theme
from metor.ui.terminal.translations import Translator

if 'terminal' not in get_registered_ui_settings():
    register_ui_settings('terminal', TERMINAL_UI_SETTINGS)

__all__ = [
    'AliasPolicy',
    'CommandDef',
    'Help',
    'PromptAbortedError',
    'PromptOutputSpacer',
    'StatusTone',
    'SubCommandDef',
    'Theme',
    'TranslationDef',
    'Translator',
    'UIPresenter',
    'extract_session_auth_prompt',
    'get_session_auth_prompt',
    'prompt_hidden',
    'prompt_hidden_optional',
    'prompt_session_auth_proof',
    'prompt_text',
]
