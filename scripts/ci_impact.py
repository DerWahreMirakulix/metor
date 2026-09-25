"""Choose a conservative branch-push check from a verified Git diff."""

import argparse
import json
from pathlib import Path, PurePosixPath
import re
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
_COMMIT_ID = re.compile(rb'[0-9a-f]{40,64}')
_REGULAR_MODES = frozenset({b'100644', b'100755'})


def _commit_id(reference: str, root: Path) -> str | None:
    """Resolve a reference to an existing commit without accepting Git options.

    Args:
        reference: Commit reference supplied by the workflow.
        root: Checked-out repository root.
    Returns:
        The full commit ID, or None when resolution fails.
    """
    try:
        result = subprocess.run(
            [
                'git',
                'rev-parse',
                '--verify',
                '--quiet',
                '--end-of-options',
                f'{reference}^{{commit}}',
            ],
            cwd=root,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    value = result.stdout.strip()
    return value.decode('ascii') if _COMMIT_ID.fullmatch(value) else None


def _regular_mode(reference: str, name: str, root: Path) -> bytes | None:
    """Read a path's Git mode without following a worktree symlink.

    Args:
        reference: Verified commit ID.
        name: Validated repository-relative path.
        root: Checked-out repository root.
    Returns:
        A regular-file mode, or None for other Git objects and errors.
    """
    try:
        result = subprocess.run(
            ['git', 'ls-tree', '-z', reference, '--', f':(literal){name}'],
            cwd=root,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    records = result.stdout.split(b'\0')
    if len(records) != 2 or records[-1] != b'':
        return None
    metadata, separator, listed_name = records[0].partition(b'\t')
    parts = metadata.split()
    if separator != b'\t' or len(parts) != 3 or parts[1] != b'blob':
        return None
    if listed_name != name.encode('utf-8'):
        return None
    return parts[0] if parts[0] in _REGULAR_MODES else None


def _parse_diff_records(data: bytes) -> list[str] | None:
    """Parse only complete, unique regular modification records.

    Args:
        data: NUL-delimited Git name-status output.
    Returns:
        Changed paths, or None for malformed or nonmodification records.
    """
    fields = data.split(b'\0')
    if fields[-1] != b'' or (len(fields) - 1) % 2:
        return None
    paths: list[str] = []
    seen: set[str] = set()
    for index in range(0, len(fields) - 1, 2):
        if fields[index] != b'M':
            return None
        try:
            name = fields[index + 1].decode('utf-8')
        except UnicodeDecodeError:
            return None
        path = PurePosixPath(name)
        if (
            not name
            or path.is_absolute()
            or path.as_posix() != name
            or any(part in ('.', '..') for part in path.parts)
            or '\\' in name
            or name in seen
        ):
            return None
        paths.append(name)
        seen.add(name)
    return paths or None


def changed_regular_paths(base: str, head: str, root: Path) -> list[str] | None:
    """Read a complete two-commit diff or require full acceptance.

    Args:
        base: Workflow diff base reference.
        head: Workflow candidate reference.
        root: Checked-out repository root.
    Returns:
        Changed regular-file paths, or None for any uncertain diff.
    """
    base_id = _commit_id(base, root)
    head_id = _commit_id(head, root)
    if not base_id or not head_id or head_id != _commit_id('HEAD', root):
        return None
    try:
        result = subprocess.run(
            [
                'git',
                'diff',
                '--no-ext-diff',
                '--no-textconv',
                '--no-renames',
                '--name-status',
                '-z',
                base_id,
                head_id,
                '--',
            ],
            cwd=root,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    paths = _parse_diff_records(result.stdout)
    if paths is None:
        return None
    for name in paths:
        old_mode = _regular_mode(base_id, name, root)
        if old_mode is None or _regular_mode(head_id, name, root) != old_mode:
            return None
    return paths


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
        if (
            path.is_symlink()
            or not path.is_file()
            or not path.resolve().is_relative_to(root.resolve())
        ):
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
    if not selected.issubset(INTEGRATION_MODULES):
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
        mode, modules = decide(
            changed_regular_paths(args.base, args.head, root) or [], root
        )
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
