"""
Module providing the frontend registry for selectable UI entry points.
Frontends register themselves under a stable identifier that the main entry
point resolves via --ui, METOR_UI, or the default terminal frontend.
"""

from typing import Callable, Dict, List


FrontendEntry = Callable[[List[str]], int]

_registry: Dict[str, FrontendEntry] = {}


def register_frontend(frontend_id: str, entry: FrontendEntry) -> None:
    """
    Registers one selectable frontend entry point under a unique identifier.

    Args:
        frontend_id (str): The unique frontend identifier used by --ui / METOR_UI.
        entry (FrontendEntry): The callable invoked with the filtered argv.

    Raises:
        ValueError: If the frontend identifier is already registered.

    Returns:
        None
    """
    if frontend_id in _registry:
        raise ValueError(f"Frontend '{frontend_id}' is already registered.")
    _registry[frontend_id] = entry


def get_frontend(frontend_id: str) -> FrontendEntry:
    """
    Resolves one registered frontend entry point by identifier.

    Args:
        frontend_id (str): The registered frontend identifier.

    Raises:
        KeyError: If no frontend is registered under the identifier.

    Returns:
        FrontendEntry: The registered entry callable.
    """
    try:
        return _registry[frontend_id]
    except KeyError:
        registered: str = ', '.join(sorted(_registry)) or 'none'
        raise KeyError(
            f"Unknown frontend '{frontend_id}'. Registered frontends: {registered}."
        ) from None


def get_registered_frontends() -> Dict[str, FrontendEntry]:
    """
    Returns a snapshot copy of all registered frontends.

    Args:
        None

    Returns:
        Dict[str, FrontendEntry]: The identifier-to-entry mapping snapshot.
    """
    return dict(_registry)
