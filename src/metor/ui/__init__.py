"""
Package initializer for the UI layer.
Exposes generic UI components, models, theming, and translation logic.
"""

from metor.ui.help import Help, CommandDef, SubCommandDef
from metor.ui.models import AliasPolicy, StatusTone, TranslationDef
from metor.ui.presenter import UIPresenter
from metor.ui.prompt import PromptAbortedError, prompt_hidden, prompt_text
from metor.ui.session_auth import prompt_session_auth_proof
from metor.ui.theme import Theme
from metor.ui.translations import Translator

__all__ = [
    'Help',
    'CommandDef',
    'SubCommandDef',
    'AliasPolicy',
    'StatusTone',
    'TranslationDef',
    'UIPresenter',
    'PromptAbortedError',
    'prompt_hidden',
    'prompt_text',
    'prompt_session_auth_proof',
    'Theme',
    'Translator',
]
