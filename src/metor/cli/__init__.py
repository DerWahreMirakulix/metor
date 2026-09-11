"""
Package initializer for the CLI module.
Exposes parsers, dispatchers, and handlers for command-line operations.
"""

from metor.cli.help import CommandDef, Help, SubCommandDef
from metor.cli.models import AliasPolicy, StatusTone, TranslationDef
from metor.cli.presenter import UIPresenter
from metor.cli.prompt import (
    PromptAbortedError,
    PromptOutputSpacer,
    prompt_hidden,
    prompt_hidden_optional,
    prompt_text,
)
from metor.cli.theme import Theme
from metor.cli.translations import Translator
from metor.cli.session_auth import (
    extract_session_auth_prompt,
    get_session_auth_prompt,
    prompt_session_auth_proof,
)
from metor.cli.dispatcher import CliDispatcher
from metor.cli.parser import CliParser
from metor.cli.entry import run_cli

__all__ = [
    'CliDispatcher',
    'CliParser',
    'CommandDef',
    'Help',
    'SubCommandDef',
    'AliasPolicy',
    'StatusTone',
    'TranslationDef',
    'UIPresenter',
    'PromptAbortedError',
    'PromptOutputSpacer',
    'Theme',
    'Translator',
    'extract_session_auth_prompt',
    'get_session_auth_prompt',
    'prompt_session_auth_proof',
    'prompt_hidden',
    'prompt_hidden_optional',
    'prompt_text',
    'run_cli',
]
