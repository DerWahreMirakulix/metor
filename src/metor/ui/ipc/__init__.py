"""Shared UI-side IPC helpers for auth-gated exchanges and stream framing."""

from metor.ui.ipc.auth import IpcAuthExchange, IpcAuthResult
from metor.ui.ipc.stream import BufferedIpcEventReader


__all__ = ['BufferedIpcEventReader', 'IpcAuthExchange', 'IpcAuthResult']
