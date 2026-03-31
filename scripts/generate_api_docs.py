"""
Script for auto-generating Markdown API documentation from the Metor IPC registries.
Enforces the DRY principle by dynamically introspecting dataclasses and Enums.
Automatically resolves project paths for the src-layout architecture.
"""

import sys
import dataclasses
from enum import Enum
from pathlib import Path
from typing import List, Type

# Local Package Imports
from metor.core.api.registry import CMD_MAP, EVENT_MAP
from metor.core.api.base import IpcMessage

# Dynamically resolve paths to support execution from any directory
SCRIPT_DIR: Path = Path(__file__).parent.resolve()
PROJECT_ROOT: Path = SCRIPT_DIR.parent
SRC_DIR: Path = PROJECT_ROOT / 'src'

# Inject the src directory into the module search path
sys.path.insert(0, str(SRC_DIR))


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
        type_str = type_str.replace('metor.core.api.events.', '')
        type_str = type_str.replace('metor.core.api.codes.', '')
        type_str = type_str.replace('metor.core.api.base.', '')

        # Coerce the expanded Union back to DomainCode for readability
        if 'SystemCode, NetworkCode, DbCode, ContactCode, UiCode' in type_str:
            type_str = type_str.replace(
                'Union[SystemCode, NetworkCode, DbCode, ContactCode, UiCode]',
                'DomainCode',
            )

        return type_str

    def _format_dataclass(self, cls: Type[IpcMessage]) -> str:
        """
        Extracts the fields, types, and defaults from a dataclass into a Markdown table.
        Filters out internal routing constants to reduce documentation noise.

        Args:
            cls (Type[IpcMessage]): The dataclass type to introspect.

        Returns:
            str: The formatted Markdown string for the class.
        """
        docstring: str = cls.__doc__ or 'No description provided.'
        lines: List[str] = [
            f'### `{cls.__name__}`',
            '',
            f'{docstring.strip()}',
            '',
            '| Field | Type | Default |',
            '|---|---|---|',
        ]

        field_count: int = 0
        for f in dataclasses.fields(cls):
            # We expose 'code' now since it defines the strict DomainCode return type.
            # Only the static routing constants 'action' and 'type' are skipped.
            if f.name in ('action', 'type'):
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
        lines: List[str] = [
            '# Metor IPC API Documentation',
            '',
            'This document is auto-generated by introspecting the `metor.core.api.registry`.',
            'It details the strict Data Transfer Objects (DTOs) used over the local IPC socket.',
            '',
            '## Table of Contents',
            '',
            '**Commands (UI -> Daemon)**',
        ]

        for cmd_cls in CMD_MAP.values():
            anchor: str = cmd_cls.__name__.lower()
            lines.append(f'- [{cmd_cls.__name__}](#{anchor})')

        lines.extend(['', '**Events (Daemon -> UI)**'])

        for event_cls in EVENT_MAP.values():
            anchor: str = event_cls.__name__.lower()
            lines.append(f'- [{event_cls.__name__}](#{anchor})')

        lines.extend(['', '## 1. Commands (UI -> Daemon)', ''])

        for index, (action, cmd_cls) in enumerate(CMD_MAP.items()):
            lines.append(self._format_dataclass(cmd_cls))
            lines.append(f'**Action Code:** `{action.value}`')
            if index < len(CMD_MAP) - 1:
                lines.append('')
                lines.append('---')

        lines.extend(['', '## 2. Events (Daemon -> UI)', ''])

        for index, (event_type, event_cls) in enumerate(EVENT_MAP.items()):
            lines.append(self._format_dataclass(event_cls))
            lines.append(f'**Event Type Code:** `{event_type.value}`')
            if index < len(EVENT_MAP) - 1:
                lines.append('')
                lines.append('---')

        with self._output_path.open('w', encoding='utf-8') as f:
            f.write('\n'.join(lines))


def main() -> None:
    """
    Entry point for the API doc generation script.

    Args:
        None

    Returns:
        None
    """
    output_file: Path = PROJECT_ROOT / 'API_DOCS.md'
    generator: ApiDocGenerator = ApiDocGenerator(output_file)
    generator.generate()
    sys.stdout.write(
        f'API documentation successfully generated at: {output_file.absolute()}\n'
    )


if __name__ == '__main__':
    main()
