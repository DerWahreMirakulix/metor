"""Frontend registry and selection facade."""

from metor.ui.registry import (
    FrontendEntry,
    get_frontend,
    get_registered_frontends,
    register_frontend,
)

__all__ = [
    'FrontendEntry',
    'get_frontend',
    'get_registered_frontends',
    'register_frontend',
]
