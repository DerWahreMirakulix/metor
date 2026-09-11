"""Structural dependency checks for disjoint SDK, base and frontend ownership."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from importlib.util import resolve_name
from pathlib import Path

SDK_ROOTS = (
    'metor.client',
    'metor.core.api',
    'metor.core.auth',
    'metor.shared',
    'metor.versioning',
)


@dataclass(frozen=True)
class Dependency:
    """One resolved import, retaining symbol and source line information."""

    module: str
    symbol: str | None
    line: int


def within(module: str, root: str) -> bool:
    """Tests a Python package boundary rather than a text prefix."""
    return module == root or module.startswith(root + '.')


def imports(
    source: str, module: str, *, package: bool = False
) -> tuple[Dependency, ...]:
    """Resolves imports structurally, including multiline and relative forms."""
    dependencies: list[Dependency] = []
    parent = module if package else module.rpartition('.')[0]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            dependencies.extend(
                Dependency(alias.name, None, node.lineno) for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            target = node.module or ''
            if node.level:
                target = resolve_name('.' * node.level + target, parent)
            dependencies.extend(
                Dependency(target, alias.name, node.lineno) for alias in node.names
            )
    return tuple(dependencies)


def violation(source: str, dependency: Dependency) -> str | None:
    """Applies owner directions and the small explicit frontend facade surface."""
    target = dependency.module
    symbol = dependency.symbol
    effective = target + '.' + symbol if symbol else target
    sdk = any(within(source, root) for root in SDK_ROOTS)
    if sdk:
        if target.split('.')[0] in {
            'dotenv',
            'sqlcipher3',
            'pysqlcipher3',
            'stem',
            'psutil',
        }:
            return 'SDK imports a host runtime dependency'
        if within(target, 'metor') and not any(
            within(target, root) or within(effective, root) for root in SDK_ROOTS
        ):
            return 'SDK imports outside SDK ownership'
    if within(source, 'metor.ui'):
        frontend = '.'.join(source.split('.')[:3])
        if within(target, 'metor.ui'):
            if not within(target, frontend) and not within(effective, frontend):
                return 'frontend imports another frontend'
        elif within(target, 'metor'):
            if any(within(target, root) for root in SDK_ROOTS):
                return None
            if target == 'metor.utils' and symbol == 'TypeCaster':
                return None  # Pure presentation enum conversion, no host service.
            return 'frontend imports host storage, lifecycle or implementation'
    elif within(target, 'metor.ui') or within(effective, 'metor.ui'):
        return 'base or SDK imports a frontend implementation'
    if any(
        within(source, root) for root in ('metor.core', 'metor.data', 'metor.utils')
    ):
        if any(
            within(target, root) or within(effective, root)
            for root in ('metor.cli', 'metor.application')
        ):
            return 'host domain imports an application adapter'
    return None


def check_source(source: str, module: str, *, package: bool = False) -> tuple[str, ...]:
    """Returns actionable violations for a source module or negative fixture."""
    errors: list[str] = []
    for dependency in imports(source, module, package=package):
        reason = violation(module, dependency)
        if reason:
            errors.append(f'{module}:{dependency.line}: {dependency.module}: {reason}')
    return tuple(errors)


def check_tree(root: Path) -> tuple[str, ...]:
    """Checks source ownership; tests and build tools are explicit composition roots."""
    errors: list[str] = []
    for path in sorted((root / 'metor').rglob('*.py')):
        parts = list(path.relative_to(root).with_suffix('').parts)
        package = parts[-1] == '__init__'
        if package:
            parts.pop()
        errors.extend(
            check_source(
                path.read_text(encoding='utf-8'), '.'.join(parts), package=package
            )
        )
    return tuple(errors)


def main() -> int:
    """Runs the executable distribution boundary gate."""
    errors = check_tree(Path(__file__).resolve().parents[1] / 'src')
    for error in errors:
        print(error)
    if not errors:
        print('Distribution and frontend boundaries passed.')
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
