"""
Package initializer for the CLI module.
Exposes parsers, dispatchers, and handlers for command-line operations.
"""

from metor.ui.terminal.cli.dispatcher import CliDispatcher
from metor.ui.terminal.cli.parser import CliParser
from metor.ui.terminal.cli.entry import run_cli

__all__ = [
    'CliDispatcher',
    'CliParser',
    'run_cli',
]
