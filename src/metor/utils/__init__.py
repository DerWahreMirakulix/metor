"""
Package initializer for the Utils layer.
Provides a unified API for constants, file locking, process management, and security helpers.
"""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from metor.utils.auth import (  # noqa: F401
        build_session_auth_proof,
        build_session_auth_proof_from_key,
        create_session_auth_challenge,
        derive_session_auth_proof_key,
        verify_session_auth_proof,
    )
    from metor.utils.caster import TypeCaster  # noqa: F401
    from metor.utils.constants import Constants  # noqa: F401
    from metor.utils.lock import FileLock  # noqa: F401
    from metor.utils.network import (  # noqa: F401
        clean_onion,
        decode_tor_v3_onion_public_key,
        ensure_onion_format,
    )
    from metor.utils.process import ProcessManager  # noqa: F401
    from metor.utils.security import (  # noqa: F401
        secure_clear_buffer,
        secure_remove_path,
        secure_shred_file,
    )
    from metor.utils.validators import validate_json_file  # noqa: F401


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    'Constants': ('metor.utils.constants', 'Constants'),
    'build_session_auth_proof': (
        'metor.utils.auth',
        'build_session_auth_proof',
    ),
    'build_session_auth_proof_from_key': (
        'metor.utils.auth',
        'build_session_auth_proof_from_key',
    ),
    'create_session_auth_challenge': (
        'metor.utils.auth',
        'create_session_auth_challenge',
    ),
    'derive_session_auth_proof_key': (
        'metor.utils.auth',
        'derive_session_auth_proof_key',
    ),
    'FileLock': ('metor.utils.lock', 'FileLock'),
    'ProcessManager': ('metor.utils.process', 'ProcessManager'),
    'TypeCaster': ('metor.utils.caster', 'TypeCaster'),
    'validate_json_file': ('metor.utils.validators', 'validate_json_file'),
    'clean_onion': ('metor.utils.network', 'clean_onion'),
    'decode_tor_v3_onion_public_key': (
        'metor.utils.network',
        'decode_tor_v3_onion_public_key',
    ),
    'ensure_onion_format': ('metor.utils.network', 'ensure_onion_format'),
    'secure_clear_buffer': ('metor.utils.security', 'secure_clear_buffer'),
    'secure_remove_path': ('metor.utils.security', 'secure_remove_path'),
    'secure_shred_file': ('metor.utils.security', 'secure_shred_file'),
    'verify_session_auth_proof': (
        'metor.utils.auth',
        'verify_session_auth_proof',
    ),
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
    'build_session_auth_proof',
    'build_session_auth_proof_from_key',
    'create_session_auth_challenge',
    'derive_session_auth_proof_key',
    'FileLock',
    'ProcessManager',
    'TypeCaster',
    'validate_json_file',
    'clean_onion',
    'decode_tor_v3_onion_public_key',
    'ensure_onion_format',
    'secure_clear_buffer',
    'secure_remove_path',
    'secure_shred_file',
    'verify_session_auth_proof',
]
