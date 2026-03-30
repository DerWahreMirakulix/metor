"""
Module defining domain-agnostic UI types and models.
Ensures that the generic UI layer does not depend on specific sub-modules like Chat or CLI.
"""

from enum import Enum
from dataclasses import dataclass


class UISeverity(str, Enum):
    """Standardized severity levels for UI translations across the application."""

    INFO = 'info'
    SYSTEM = 'system'
    ERROR = 'error'


@dataclass
class TranslationDef:
    """Strongly typed definition for a UI translation string."""

    text: str
    severity: UISeverity
