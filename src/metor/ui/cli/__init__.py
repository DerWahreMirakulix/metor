"""
Package initializer for the CLI module.
Exposes parsers, dispatchers, and handlers for command-line operations.
"""

from metor.ui.cli.dispatcher import CliDispatcher
from metor.ui.cli.handlers import CommandHandlers
from metor.ui.cli.parser import CliParser
from metor.ui.cli.proxy import CliProxy

__all__ = [
    'CliDispatcher',
    'CommandHandlers',
    'CliParser',
    'CliProxy',
]
