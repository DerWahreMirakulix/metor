"""
Package initializer for the Metor Client SDK layer.
Provides a unified, terminal-free client library for connecting to a Metor daemon.
"""

from metor.client.auth import (
    AuthProvider,
    IpcAuthExchange,
    IpcAuthResult,
    build_session_auth_proof,
    build_session_auth_proof_from_key,
    derive_session_auth_proof_key,
    extract_session_auth_prompt,
)
from metor.client.ipc import IpcClient
from metor.client.session import MetorClient, parse_endpoint
from metor.client.stream import BufferedIpcEventReader

__all__ = [
    'AuthProvider',
    'BufferedIpcEventReader',
    'IpcAuthExchange',
    'IpcAuthResult',
    'IpcClient',
    'MetorClient',
    'build_session_auth_proof',
    'build_session_auth_proof_from_key',
    'derive_session_auth_proof_key',
    'extract_session_auth_prompt',
    'parse_endpoint',
]
