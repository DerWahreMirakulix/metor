"""
Module defining domain-agnostic UI types and models.
Ensures that the generic UI layer does not depend on specific sub-modules like Chat or CLI.
"""

from dataclasses import dataclass
from enum import Enum


class StatusTone(str, Enum):
    """Standardized tone levels for translated daemon status messages."""

    INFO = 'info'
    SYSTEM = 'system'
    ERROR = 'error'


@dataclass
class TranslationDef:
    """
    Strongly typed definition for a UI translation string.

    Attributes:
        text (str): The raw translation string with optional formatting placeholders.
        tone (StatusTone): The tone used by the consuming UI.
    """

    text: str
    tone: StatusTone
