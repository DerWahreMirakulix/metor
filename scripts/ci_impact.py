"""Choose a conservative branch-push check from a verified Git diff."""

import argparse
import json
from pathlib import Path
import subprocess

from scripts.run_tests import INTEGRATION_MODULES


ISOLATED_GUI_MODULES: dict[str, tuple[str, ...]] = {
    'src/metor/ui/gui/views/root/panel.py': ('test_gui_contract', 'test_gui_root'),
    'src/metor/ui/gui/views/root/row.py': ('test_gui_contract', 'test_gui_root'),
    'src/metor/ui/gui/theme.py': ('test_gui_contract', 'test_gui_pages'),
}
ISOLATED_GUI_TESTS = frozenset(
    {'test_gui_buttons', 'test_gui_fonts', 'test_gui_pages', 'test_gui_root'}
)


def decide(paths: list[str], root: Path) -> tuple[str, tuple[str, ...]]:
    """Map known isolated edits to a fast check and integration modules.

    Args:
        paths: Changed repository-relative paths.
        root: Checked-out repository root.
    Returns:
        Full or fast mode and explicit integration modules.
    """
    if not paths:
        return 'full', ()
    selected: set[str] = set()
    for name in paths:
        path = root / name
        if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            return 'full', ()
        if name == 'docs/GLOSSARY.md':
            continue
        if name in ISOLATED_GUI_MODULES:
            selected.update(ISOLATED_GUI_MODULES[name])
            continue
        if name == 'src/metor/ui/terminal/chat/renderer/display.py':
            selected.add('test_terminal_rendering_security')
            continue
        if name.startswith('tests/test_gui_') and name.endswith('.py'):
            module = Path(name).stem
            if module not in ISOLATED_GUI_TESTS or module not in INTEGRATION_MODULES:
                return 'full', ()
            selected.add(module)
            continue
        return 'full', ()
    return 'fast', tuple(sorted(selected))


def main() -> int:
    """Write a GitHub Actions plan after checking the complete diff basis.

    Args:
        None
    Returns:
        Process status.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base')
    parser.add_argument('--head')
    parser.add_argument('--full', action='store_true')
    parser.add_argument('--github-output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    mode: str
    modules: tuple[str, ...]
    if args.full or not args.base or not args.head:
        mode, modules = 'full', ()
    else:
        try:
            diff = subprocess.run(
                ['git', 'diff', '--name-only', args.base, args.head, '--'],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
            )
            mode, modules = decide(diff.stdout.splitlines(), root)
        except (OSError, subprocess.CalledProcessError):
            mode, modules = 'full', ()
    matrix = (
        {
            'include': [
                {'os': os_name, 'python-version': version}
                for os_name in ('ubuntu-latest', 'windows-latest')
                for version in ('3.11', '3.13')
            ]
        }
        if mode == 'full'
        else {'include': [{'os': 'ubuntu-latest', 'python-version': '3.11'}]}
    )
    with args.github_output.open('a', encoding='utf-8') as stream:
        stream.write(f'mode={mode}\n')
        stream.write(f'matrix={json.dumps(matrix, separators=(",", ":"))}\n')
        stream.write(f'modules={" ".join(modules)}\n')
    print(f'CI plan: {mode}; selected integration modules: {", ".join(modules)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
