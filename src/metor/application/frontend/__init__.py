"""Public base-owned frontend host and creation entry point."""

from .host import LocalFrontendHost, create_local_frontend_host

__all__ = ['LocalFrontendHost', 'create_local_frontend_host']
