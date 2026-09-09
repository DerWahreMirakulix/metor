"""Package facade for CLI-side typed IPC request exchanges."""

from metor.ui.terminal.cli.ipc.request.models import IpcRequestResult
from metor.ui.terminal.cli.ipc.request.session import IpcRequestSession


__all__ = ['IpcRequestResult', 'IpcRequestSession']
