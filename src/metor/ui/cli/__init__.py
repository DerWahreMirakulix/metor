"""
Package initializer for the CLI module.
Exposes parsers, dispatchers, and handlers for command-line operations.
"""

from metor.ui.cli.dispatcher import CliDispatcher
from metor.ui.cli.parser import CliParser
from metor.ui.cli.entry import run_cli

__all__ = [
    'CliDispatcher',
    'CliParser',
    'run_cli',
]
