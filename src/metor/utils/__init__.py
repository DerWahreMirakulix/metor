"""Lazy facade for Base-owned host runtime utilities."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from metor.utils.caster import TypeCaster  # noqa: F401
    from metor.utils.constants import Constants  # noqa: F401
    from metor.utils.lock import FileLock  # noqa: F401
    from metor.utils.process import ProcessManager  # noqa: F401
    from metor.utils.security import (  # noqa: F401
        secure_remove_path,
        secure_shred_file,
    )
    from metor.utils.validators import validate_json_file  # noqa: F401


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    'Constants': ('metor.utils.constants', 'Constants'),
    'FileLock': ('metor.utils.lock', 'FileLock'),
    'ProcessManager': ('metor.utils.process', 'ProcessManager'),
    'TypeCaster': ('metor.utils.caster', 'TypeCaster'),
    'validate_json_file': ('metor.utils.validators', 'validate_json_file'),
    'secure_remove_path': ('metor.utils.security', 'secure_remove_path'),
    'secure_shred_file': ('metor.utils.security', 'secure_shred_file'),
}


def __getattr__(name: str) -> Any:
    """
    Resolves public utils exports lazily to avoid importing optional runtime deps during tooling bootstrap.

    Args:
        name (str): The requested public attribute name.

    Raises:
        AttributeError: If the name is not part of the public utils API.

    Returns:
        Any: The resolved exported object.
    """
    export = _LAZY_EXPORTS.get(name)
    if export is None:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')

    module_name, attribute_name = export
    value: Any = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """
    Returns the exposed utils API for interactive inspection and star imports.

    Args:
        None

    Returns:
        list[str]: The sorted public attribute names.
    """
    return sorted(set(globals()) | set(_LAZY_EXPORTS))


__all__ = [
    'Constants',
    'FileLock',
    'ProcessManager',
    'TypeCaster',
    'validate_json_file',
    'secure_remove_path',
    'secure_shred_file',
]
