"""
Script for auto-generating Markdown settings documentation from Metor setting metadata.
Builds a human-readable reference for both global settings and profile structural config.
Automatically resolves project paths for the src-layout architecture and applies
Prettier formatting to the final output.
"""

# ruff: noqa: E402

import sys
import subprocess
from pathlib import Path
from typing import Dict, List


SCRIPT_DIR: Path = Path(__file__).parent.resolve()
PROJECT_ROOT: Path = SCRIPT_DIR.parent
SRC_DIR: Path = PROJECT_ROOT / 'src'


sys.path.insert(0, str(SRC_DIR))

from metor.data import Settings, SettingSpec
from metor.data.profile import (
    PROFILE_CONFIG_SPECS,
    ProfileConfigKey,
    ProfileConfigSpec,
)


class SettingsDocGenerator:
    """Generates Markdown documentation for settings and profile config metadata."""

    def __init__(self, output_path: str | Path) -> None:
        """
        Initializes the documentation generator.

        Args:
            output_path (str | Path): The absolute or relative path for the generated Markdown file.

        Returns:
            None
        """
        self._output_path: Path = Path(output_path)

    @staticmethod
    def _format_default(value: object) -> str:
        """
        Formats a default value for Markdown tables.

        Args:
            value (object): The raw default value.

        Returns:
            str: A Markdown-safe value string.
        """
        return f'`{value}`' if value is not None else '`None`'

    @staticmethod
    def _setting_type_name(spec: SettingSpec) -> str:
        """
        Returns the type label for one setting specification.

        Args:
            spec (SettingSpec): The setting specification.

        Returns:
            str: The type label.
        """
        default_type: type = type(spec.default)
        return default_type.__name__

    @staticmethod
    def _profile_type_name(spec: ProfileConfigSpec) -> str:
        """
        Returns the type label for one profile configuration specification.

        Args:
            spec (ProfileConfigSpec): The profile configuration specification.

        Returns:
            str: The type label.
        """
        if spec.key is ProfileConfigKey.IS_REMOTE:
            return 'bool'
        if spec.key is ProfileConfigKey.DAEMON_PORT:
            return 'Optional[int]'
        if spec.key is ProfileConfigKey.SECURITY_MODE:
            return "Literal['encrypted', 'plaintext']"
        return 'value'

    @staticmethod
    def _setting_scope(spec: SettingSpec) -> str:
        """
        Returns the scope label for one setting.

        Args:
            spec (SettingSpec): The setting specification.

        Returns:
            str: The scope label.
        """
        if spec.key.is_ui:
            return 'UI client-local'
        return 'Daemon runtime'

    @staticmethod
    def _setting_cli_examples(spec: SettingSpec) -> List[str]:
        """
        Builds compact CLI examples for one setting.

        Args:
            spec (SettingSpec): The setting specification.

        Returns:
            List[str]: The example command lines.
        """
        default_text: str = (
            str(spec.default).lower()
            if isinstance(spec.default, bool)
            else str(spec.default)
        )
        examples: List[str] = [
            f'`metor settings get {spec.key.value}`',
            f'`metor settings set {spec.key.value} {default_text}`',
        ]

        if spec.allow_profile_override:
            examples.extend(
                [
                    f'`metor -p <profile> config get {spec.key.value}`',
                    f'`metor -p <profile> config set {spec.key.value} {default_text}`',
                ]
            )

        return examples

    @staticmethod
    def _profile_cli_examples(spec: ProfileConfigSpec) -> List[str]:
        """
        Builds compact CLI examples for one structural profile config key.

        Args:
            spec (ProfileConfigSpec): The profile configuration specification.

        Returns:
            List[str]: The example command lines.
        """
        if spec.key is ProfileConfigKey.IS_REMOTE:
            return ['`metor profiles add <name> --remote --port <port>`']

        if spec.key is ProfileConfigKey.SECURITY_MODE:
            return [
                '`metor profiles add <name> --plaintext`',
                '`metor profiles migrate <name> --to <encrypted|plaintext>`',
            ]

        return [
            f'`metor -p <profile> config get {spec.key.value}`',
            f'`metor -p <profile> config set {spec.key.value} 50051`',
        ]

    @staticmethod
    def _heading_anchor(value: str) -> str:
        """
        Builds one predictable Markdown heading anchor.

        Args:
            value (str): The raw heading text.

        Returns:
            str: The normalized heading anchor without the leading '#'.
        """
        return (
            value.strip()
            .lower()
            .replace('`', '')
            .replace('&', '')
            .replace('.', '')
            .replace(',', '')
            .replace('(', '')
            .replace(')', '')
            .replace('/', '')
            .replace(' ', '-')
        )

    def _format_setting(self, spec: SettingSpec) -> str:
        """
        Formats one setting entry as Markdown.

        Args:
            spec (SettingSpec): The setting specification.

        Returns:
            str: The rendered Markdown block.
        """
        lines: List[str] = [
            f'#### `{spec.key.value}`',
            '',
            f'{spec.description}',
            '',
            '| Property | Value |',
            '|---|---|',
            f'| Type | `{self._setting_type_name(spec)}` |',
            f'| Default | {self._format_default(spec.default)} |',
            f'| Category | `{spec.category}` |',
            f'| Scope | `{self._setting_scope(spec)}` |',
            f'| Profile Override | `{"Yes" if spec.allow_profile_override else "No"}` |',
            f'| Constraints | {spec.constraints} |',
        ]

        if spec.security_note:
            lines.append(f'| Security Note | {spec.security_note} |')

        lines.extend(['', '**CLI Examples**', ''])
        for example in self._setting_cli_examples(spec):
            lines.append(f'- {example}')
        lines.append('')
        return '\n'.join(lines)

    def _format_profile_config(self, spec: ProfileConfigSpec) -> str:
        """
        Formats one profile structural config entry as Markdown.

        Args:
            spec (ProfileConfigSpec): The profile configuration specification.

        Returns:
            str: The rendered Markdown block.
        """
        lines: List[str] = [
            f'### `{spec.key.value}`',
            '',
            f'{spec.description}',
            '',
            '| Property | Value |',
            '|---|---|',
            f'| Type | `{self._profile_type_name(spec)}` |',
            f'| Default | {self._format_default(spec.default)} |',
            '| Scope | `Profile structural config` |',
            f'| Mutable After Creation | `{"Yes" if spec.mutable_after_creation else "No"}` |',
            f'| Constraints | {spec.constraints} |',
            '',
            '**CLI Examples**',
            '',
        ]
        for example in self._profile_cli_examples(spec):
            lines.append(f'- {example}')
        lines.append('')
        return '\n'.join(lines)

    def generate(self) -> None:
        """
        Builds and writes the Markdown settings reference.

        Args:
            None

        Returns:
            None
        """
        settings_by_category: Dict[str, List[SettingSpec]] = {}
        for spec in Settings.get_specs():
            settings_by_category.setdefault(spec.category, []).append(spec)

        lines: List[str] = [
            '# Metor Settings Documentation',
            '',
            'This document is auto-generated from setting metadata in `metor.data.settings` and `metor.data.profile.models`.',
            'It is the canonical reference for supported user-facing settings and structural profile config keys.',
            '',
            '## Configuration Model',
            '',
            '- `metor settings ...` changes global defaults. `ui.*` keys are stored in the local client `settings.json`, while `daemon.*` keys are resolved on the targeted daemon host.',
            '- `metor config ...` writes profile-specific overrides in the active profile `config.json`.',
            '- `metor settings list` shows the current global UI settings plus the current global daemon settings for the targeted runtime.',
            '- `metor config list` shows the effective values for the active profile, including local UI overrides, daemon-side effective values, and structural profile metadata.',
            '- UI settings stay local to the client machine. Daemon settings are applied to the owning daemon runtime.',
            '- Structural profile config keys are special-case profile metadata, not regular cascading settings.',
            '',
            '## Table of Contents',
            '',
            '- [Configuration Model](#configuration-model)',
            '- [Cascading Settings](#cascading-settings)',
        ]

        for category in settings_by_category.keys():
            lines.append(f'  - [{category}](#{self._heading_anchor(category)})')

        lines.extend(
            [
                '- [Structural Profile Config](#structural-profile-config)',
                '',
                '## Cascading Settings',
                '',
            ]
        )

        for category, specs in settings_by_category.items():
            lines.append(f'### {category}')
            lines.append('')
            for index, spec in enumerate(specs):
                lines.append(self._format_setting(spec))
                if index < len(specs) - 1:
                    lines.append('---')
                    lines.append('')
            lines.append('')

        lines.extend(['## Structural Profile Config', ''])

        profile_specs: List[ProfileConfigSpec] = list(PROFILE_CONFIG_SPECS.values())
        for index, profile_spec in enumerate(profile_specs):
            lines.append(self._format_profile_config(profile_spec))
            if index < len(profile_specs) - 1:
                lines.append('---')
                lines.append('')

        with self._output_path.open('w', encoding='utf-8') as handle:
            handle.write('\n'.join(lines))


def main() -> None:
    """
    Entry point for the settings doc generation script.

    Args:
        None

    Returns:
        None
    """
    output_file: Path = PROJECT_ROOT / 'docs' / 'SETTINGS.md'
    generator: SettingsDocGenerator = SettingsDocGenerator(output_file)
    generator.generate()
    sys.stdout.write(
        f'Settings documentation successfully generated at: {output_file.absolute()}\n'
    )

    sys.stdout.write('Running Prettier on the generated file...\n')
    try:
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
