"""
Script for auto-generating Markdown API documentation from the Metor IPC registries.
Enforces the DRY principle by dynamically introspecting dataclasses and Enums.
Automatically resolves project paths for the src-layout architecture and applies
Prettier formatting to the final output.
"""

# ruff: noqa: E402

import sys
import json
import inspect
import subprocess
import dataclasses
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Type, Any, get_args, get_origin


# Dynamically resolve paths to support execution from any directory
SCRIPT_DIR: Path = Path(__file__).parent.resolve()
PROJECT_ROOT: Path = SCRIPT_DIR.parent
SRC_DIR: Path = PROJECT_ROOT / 'src'


# Inject the src directory into the module search path
sys.path.insert(0, str(SRC_DIR))

from metor.core.api import CMD_MAP, EVENT_MAP

if TYPE_CHECKING:
    from metor.core.api import IpcMessage


class ApiDocGenerator:
    """Generates Markdown API documentation by inspecting the core IPC DTOs."""

    def __init__(self, output_path: str | Path) -> None:
        """
        Initializes the documentation generator.

        Args:
            output_path (str | Path): The absolute or relative path for the generated Markdown file.

        Returns:
            None
        """
        self._output_path: Path = Path(output_path)

    def _get_type_name(self, field_type: object) -> str:
        """
        Extracts a clean string representation of a type hint, stripping verbose typing prefixes
        and internal module paths to maintain readability in the generated documentation.

        Args:
            field_type (object): The type annotation from the dataclass field.

        Returns:
            str: The formatted stringified type.
        """
        origin: Any = get_origin(field_type)
        args: tuple[Any, ...] = get_args(field_type)

        if origin is list and args:
            return f'List[{self._get_type_name(args[0])}]'
        if origin is dict and len(args) == 2:
            return (
                f'Dict[{self._get_type_name(args[0])}, {self._get_type_name(args[1])}]'
            )
        if origin is tuple and args:
            joined_args: str = ', '.join(self._get_type_name(arg) for arg in args)
            return f'Tuple[{joined_args}]'
        if origin is not None and args:
            origin_name: str = getattr(origin, '__name__', str(origin))
            joined_args = ', '.join(self._get_type_name(arg) for arg in args)
            return f'{origin_name}[{joined_args}]'

        type_str: str = str(field_type)

        # Explicitly catch the complex JsonValue resolution
        if 'ForwardRef' in type_str and 'JsonValue' in type_str:
            return 'Dict[str, JsonValue]'

        # Handle built-in classes vs typing module classes
        if type_str.startswith("<class '") and type_str.endswith("'>"):
            type_str = type_str.split("'")[1]
            if '.' in type_str:
                type_str = type_str.split('.')[-1]

        # Strip standard typing prefixes
        type_str = type_str.replace('typing.', '')
        type_str = type_str.replace('NoneType', 'None')

        # Clean up absolute module paths for new DTO Sub-Models and Enums
        type_str = type_str.replace('metor.core.api.events.entries.', '')
        type_str = type_str.replace('metor.core.api.events.', '')
        type_str = type_str.replace('metor.core.api.events.history.', '')
        type_str = type_str.replace('metor.core.api.codes.', '')
        type_str = type_str.replace('metor.core.api.base.', '')

        return type_str

    def _sample_value(self, field_type: object) -> Any:
        """
        Builds a compact example value for a dataclass field annotation.

        Args:
            field_type (object): The dataclass field annotation.

        Returns:
            Any: A JSON-serializable sample value.
        """
        origin: Any = get_origin(field_type)
        args: tuple[Any, ...] = get_args(field_type)

        if origin is list and args:
            return [self._sample_value(args[0])]
        if origin is dict and len(args) == 2:
            return {'key': self._sample_value(args[1])}
        if origin is tuple and args:
            return [self._sample_value(arg) for arg in args]
        if origin is not None and args:
            non_none_args: List[Any] = [arg for arg in args if arg is not type(None)]
            return self._sample_value(non_none_args[0]) if non_none_args else None
        if isinstance(field_type, type) and issubclass(field_type, Enum):
            return next(iter(field_type)).value
        if field_type is str:
            return 'string'
        if field_type is int:
            return 0
        if field_type is float:
            return 0.0
        if field_type is bool:
            return False
        if field_type is type(None):
            return None
        return 'value'

    def _build_example_payload(
        self,
        cls: Type['IpcMessage'],
        route_key: str,
        route_value: str,
    ) -> str:
        """
        Builds a compact JSON example for one command or event DTO.

        Args:
            cls (Type[IpcMessage]): The dataclass type to introspect.
            route_key (str): The envelope routing key.
            route_value (str): The concrete routing value.

        Returns:
            str: A formatted JSON example string.
        """
        payload: Dict[str, Any] = {route_key: route_value}

        for field in dataclasses.fields(cls):
            if field.name in ('command_type', 'event_type'):
                continue

            if (
                field.default is dataclasses.MISSING
                and field.default_factory is dataclasses.MISSING
            ):
                payload[field.name] = self._sample_value(field.type)

        return json.dumps(payload, indent=2)

    def _format_dataclass(self, cls: Type['IpcMessage']) -> str:
        """
        Extracts the fields, types, and defaults from a dataclass into a Markdown table.
        Filters out internal routing constants to reduce documentation noise.

        Args:
            cls (Type[IpcMessage]): The dataclass type to introspect.

        Returns:
            str: The formatted Markdown string for the class.
        """
        docstring: str = inspect.getdoc(cls) or 'No description provided.'
        lines: List[str] = [
            f'### `{cls.__name__}`',
            '',
            f'{docstring}',
            '',
            '| Field | Type | Default |',
            '|---|---|---|',
        ]

        field_count: int = 0
        for f in dataclasses.fields(cls):
            if f.name in ('command_type', 'event_type'):
                continue

            field_count += 1
            type_name: str = self._get_type_name(f.type)

            default_val: str = 'Required'
            if isinstance(f.default, Enum):
                default_val = f'`{f.default.__class__.__name__}.{f.default.name}`'
            elif f.default is not dataclasses.MISSING:
                default_val = f'`{f.default}`'
            elif f.default_factory is not dataclasses.MISSING:
                default_val = '`Factory()`'

            lines.append(f'| `{f.name}` | `{type_name}` | {default_val} |')

        if field_count == 0:
            lines.pop()
            lines.pop()
            lines.append('*No additional payload parameters.*')

        lines.append('')
        return '\n'.join(lines)

    def generate(self) -> None:
        """
        Iterates over the command and event registries, builds the Markdown layout
        with a Table of Contents, and writes it to the designated file.

        Args:
            None

        Returns:
            None
        """
        sorted_commands = sorted(CMD_MAP.items(), key=lambda item: item[0].value)
        sorted_events = sorted(EVENT_MAP.items(), key=lambda item: item[0].value)

        lines: List[str] = [
            '# Metor IPC API Documentation',
            '',
            'This document is auto-generated by introspecting the `metor.core.api.registry`.',
            'It describes the strict newline-delimited JSON protocol used over the local IPC socket.',
            '',
            '## Protocol Notes',
            '',
            '- Commands sent from the UI to the daemon must include a top-level `command_type` field.',
            '- Events sent from the daemon to the UI must include a top-level `event_type` field.',
            '- Every payload is a single JSON object followed by a newline (`\\n`).',
            '- The daemon emits structured data only. Human-readable text is resolved in the UI from `event_type`.',
            '',
            '## Table of Contents',
            '',
            '**Commands (UI -> Daemon)**',
        ]

        for _, cmd_cls in sorted_commands:
            cmd_anchor: str = cmd_cls.__name__.lower()
            lines.append(f'- [{cmd_cls.__name__}](#{cmd_anchor})')

        lines.extend(['', '**Events (Daemon -> UI)**'])

        for _, event_cls in sorted_events:
            evt_anchor: str = event_cls.__name__.lower()
            lines.append(f'- [{event_cls.__name__}](#{evt_anchor})')

        lines.extend(['', '## 1. Commands (UI -> Daemon)', ''])

        for index, (command_type, cmd_cls) in enumerate(sorted_commands):
            lines.append(self._format_dataclass(cmd_cls))
            lines.append(f'**Wire Value:** `{command_type.value}`')
            lines.append('')
            lines.append('**Example JSON**')
            lines.append('')
            lines.append('```json')
            lines.append(
                self._build_example_payload(
                    cmd_cls,
                    'command_type',
                    command_type.value,
                )
            )
            lines.append('```')
            if index < len(sorted_commands) - 1:
                lines.append('')
                lines.append('---')

        lines.extend(['', '## 2. Events (Daemon -> UI)', ''])

        for index, (event_type, event_cls) in enumerate(sorted_events):
            lines.append(self._format_dataclass(event_cls))
            lines.append(f'**Wire Value:** `{event_type.value}`')
            lines.append('')
            lines.append('**Example JSON**')
            lines.append('')
            lines.append('```json')
            lines.append(
                self._build_example_payload(
                    event_cls,
                    'event_type',
                    event_type.value,
                )
            )
            lines.append('```')
            if index < len(sorted_events) - 1:
                lines.append('')
                lines.append('---')

        with self._output_path.open('w', encoding='utf-8') as f:
            f.write('\n'.join(lines))


def main() -> None:
    """
    Entry point for the API doc generation script.
    Generates the Markdown file and formats it using Prettier.

    Args:
        None

    Returns:
        None
    """
    output_file: Path = PROJECT_ROOT / 'docs' / 'API.md'
    generator: ApiDocGenerator = ApiDocGenerator(output_file)
    generator.generate()
    sys.stdout.write(
        f'API documentation successfully generated at: {output_file.absolute()}\n'
    )

    sys.stdout.write('Running Prettier on the generated file...\n')
    try:
        # Cross-platform binary resolution for npx
        npx_cmd: str = 'npx.cmd' if sys.platform == 'win32' else 'npx'

        subprocess.run(
            [npx_cmd, 'prettier', '--write', str(output_file.absolute())],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        sys.stdout.write('Prettier formatting applied successfully.\n')
    except subprocess.CalledProcessError:
        sys.stdout.write(
            f'Warning: Prettier formatting failed for {output_file.name}. Ensure it is configured correctly.\n'
        )
    except FileNotFoundError:
        sys.stdout.write(
            'Warning: npx command not found. Skipping Prettier formatting. (Is Node.js installed?)\n'
        )


if __name__ == '__main__':
    main()
