"""
Module defining domain-agnostic UI types and models.
Ensures that the generic UI layer does not depend on specific sub-modules like Chat or CLI.
"""

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class CliCommandResult:
    """Rendered local command outcome, independent of wording or IPC events.

    Attributes:
        message: The complete terminal-safe output for the dispatcher.
        failed: Whether local interaction prevented completing the command.
    """

    message: str
    failed: bool = False


class StatusTone(str, Enum):
    """Standardized tone levels for translated daemon status messages."""

    INFO = 'info'
    SYSTEM = 'system'
    ERROR = 'error'


class AliasPolicy(str, Enum):
    """Controls whether a rendered UI line binds to no peer, a fixed alias snapshot, or a rename-safe dynamic peer identity."""

    NONE = 'none'
    STATIC = 'static'
    DYNAMIC = 'dynamic'


@dataclass
class TranslationDef:
    """
    Strongly typed definition for a UI translation string.

    Attributes:
        text (str): The raw translation string with optional formatting placeholders.
        tone (StatusTone): The tone used by the consuming UI.
        alias_policy (AliasPolicy): Whether alias placeholders stay dynamic in chat.
    """

    text: str
    tone: StatusTone
    alias_policy: AliasPolicy = AliasPolicy.NONE
