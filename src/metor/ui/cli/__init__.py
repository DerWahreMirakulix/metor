"""
Package initializer for the CLI module.
Exposes parsers, dispatchers, and handlers for command-line operations.
"""

from metor.ui.cli.dispatcher import CliDispatcher
from metor.ui.cli.parser import CliParser

__all__ = [
    'CliDispatcher',
    'CliParser',
]
