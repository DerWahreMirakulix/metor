"""Build the canonical Metor command-line grammar from shared definitions."""

import argparse
import sys
from typing import Any, Dict, List, Optional, Tuple

# Local Package Imports
from metor.cli.help import OPTION_DEFAULT_UNSET, CommandDef, Help, OptionDef


class CliParser:
    """Constructs and executes the public command-line parser."""

    @staticmethod
    def _add_option(
        target: argparse.ArgumentParser | argparse._MutuallyExclusiveGroup,
        option: OptionDef,
    ) -> None:
        """Adds one canonical option definition to an argparse target.

        Args:
            target (argparse.ArgumentParser | argparse._MutuallyExclusiveGroup): Parser or mutually exclusive group receiving the option.
            option (OptionDef): Canonical option definition.

        Returns:
            None
        """
        help_text: str = argparse.SUPPRESS if option.hidden else option.description
        default: Dict[str, Any] = {}
        if option.default is not OPTION_DEFAULT_UNSET:
            default['default'] = option.default
        if option.action == 'store_true':
            target.add_argument(
                *option.flags,
                dest=option.destination,
                action='store_true',
                help=help_text,
                **default,
            )
            return
        if option.action == 'store_false':
            target.add_argument(
                *option.flags,
                dest=option.destination,
                action='store_false',
                help=help_text,
                **default,
            )
            return
        value_type: type[str] | type[int] = int if option.value_type == 'int' else str
        target.add_argument(
            *option.flags,
            dest=option.destination,
            metavar=option.metavar,
            type=value_type,
            help=help_text,
            **default,
        )

    @classmethod
    def _build_options_parser(
        cls,
        *,
        prog: str,
        options: Tuple[OptionDef, ...],
    ) -> argparse.ArgumentParser:
        """Builds an argparse parser for one canonical option collection.

        Args:
            prog (str): Program label used by argparse diagnostics.
            options (Tuple[OptionDef, ...]): Canonical options to register.

        Returns:
            argparse.ArgumentParser: Configured parser without automatic help.
        """
        parser = argparse.ArgumentParser(prog=prog, add_help=False)
        groups: Dict[str, argparse._MutuallyExclusiveGroup] = {}
        for option in options:
            target: argparse.ArgumentParser | argparse._MutuallyExclusiveGroup = parser
            if option.group is not None:
                if option.group not in groups:
                    groups[option.group] = parser.add_mutually_exclusive_group()
                target = groups[option.group]
            cls._add_option(target, option)
        return parser

    @staticmethod
    def _split_literal_arguments(argv: List[str]) -> Tuple[List[str], List[str]]:
        """Splits argv at the first option terminator without retaining it.

        Args:
            argv (List[str]): Raw arguments excluding the executable name.

        Returns:
            Tuple[List[str], List[str]]: Grammar tokens and literal payload tokens.
        """
        try:
            separator_index: int = argv.index('--')
        except ValueError:
            return list(argv), []
        return list(argv[:separator_index]), list(argv[separator_index + 1 :])

    @classmethod
    def parse(
        cls,
        argv: Optional[List[str]] = None,
    ) -> Tuple[argparse.Namespace, List[str]]:
        """Parses argv through the canonical global and command definitions.

        The first ``--`` ends all option interpretation. Tokens after it are
        returned as literal command data and cannot select help, version, a
        profile, or an execution mode.

        Args:
            argv (Optional[List[str]]): Argument vector excluding the program name, or None to use the process argv.

        Returns:
            Tuple[argparse.Namespace, List[str]]: Parsed arguments and lossless command operands after the first positional token.
        """
        raw_argv: List[str] = list(argv) if argv is not None else sys.argv[1:]
        grammar_tokens, literal_tokens = cls._split_literal_arguments(raw_argv)
        parser = cls._build_options_parser(
            prog='metor',
            options=Help.GLOBAL_OPTIONS,
        )
        args, command_tokens = parser.parse_known_args(grammar_tokens)

        args.command = command_tokens[0] if command_tokens else 'quickstart'
        command_operands: List[str] = command_tokens[1:]
        command_definition: Optional[CommandDef] = Help.CLI_COMMANDS.get(args.command)
        if command_definition is not None and command_definition.options:
            command_parser = cls._build_options_parser(
                prog=f'metor {args.command}',
                options=command_definition.options,
            )
            command_args, command_operands = command_parser.parse_known_args(
                command_operands
            )
            for name, value in vars(command_args).items():
                setattr(args, name, value)

        defaults: Dict[str, object] = {
            'ui': None,
            'list_uis': False,
            'device_config': None,
            'simulator': False,
            'locked': False,
            'non_interactive': False,
            'startup_session_auth_stdin': False,
            'force': False,
        }
        for name, value in defaults.items():
            if not hasattr(args, name):
                setattr(args, name, value)

        operands: List[str] = command_operands + literal_tokens
        args.literal_args = list(literal_tokens)
        args.subcommand = operands[0] if operands else None
        args.extra = list(operands) if args.command == 'chat' else operands[1:]
        args.chat_help = args.command == 'chat' and args.help_requested
        return args, args.extra
