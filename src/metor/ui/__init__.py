"""
Package initializer for the UI layer.
Exposes generic UI components, models, theming, and translation logic.
"""

from metor.data import (
    TERMINAL_UI_SETTINGS,
    get_registered_ui_settings,
    register_ui_settings,
)
from metor.ui.help import Help, CommandDef, SubCommandDef
from metor.ui.models import AliasPolicy, StatusTone, TranslationDef
from metor.ui.presenter import UIPresenter
from metor.ui.prompt import (
    PromptAbortedError,
    PromptOutputSpacer,
    prompt_hidden,
    prompt_hidden_optional,
    prompt_text,
)
from metor.ui.session_auth import (
    extract_session_auth_prompt,
    get_session_auth_prompt,
    prompt_session_auth_proof,
)
from metor.ui.theme import Theme
from metor.ui.translations import Translator
from metor.ui.cli.entry import run_cli
from metor.ui.registry import (
    FrontendEntry,
    get_frontend,
    get_registered_frontends,
    register_frontend,
)

# Idempotently register the terminal frontend's UI setting specs so namespace
# routing (`ui.<frontend>.<key>`) is available before any proxy or chat code
# runs, no matter which UI submodule is imported first.
if 'terminal' not in get_registered_ui_settings():
    register_ui_settings('terminal', TERMINAL_UI_SETTINGS)

# Idempotently register the terminal frontend entry so the default UI is
# resolvable through the frontend registry before any CLI code runs.
if 'terminal' not in get_registered_frontends():
    register_frontend('terminal', run_cli)

__all__ = [
    'Help',
    'CommandDef',
    'SubCommandDef',
    'AliasPolicy',
    'StatusTone',
    'TranslationDef',
    'UIPresenter',
    'PromptAbortedError',
    'PromptOutputSpacer',
    'prompt_hidden',
    'prompt_hidden_optional',
    'prompt_text',
    'extract_session_auth_prompt',
    'get_session_auth_prompt',
    'prompt_session_auth_proof',
    'Theme',
    'Translator',
    'FrontendEntry',
    'get_frontend',
    'get_registered_frontends',
    'register_frontend',
]
