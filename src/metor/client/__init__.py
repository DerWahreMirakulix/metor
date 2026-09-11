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
    build_pin_unlock_proof,
    create_pin_verifier,
    derive_pin_verifier,
    derive_session_auth_proof_key,
    extract_session_auth_prompt,
)
from metor.client.ipc import IpcClient
from metor.client.ipc import (
    IpcClientError,
    IpcDisconnectedError,
    IpcRequestLimitError,
    IpcSendError,
    IpcTimeoutError,
)
from metor.client.contact_qr import (
    ContactQrError,
    ContactQrPayload,
    ContactQrValidationResult,
    validate_contact_qr,
)
from metor.client.session import MetorClient, parse_endpoint
from metor.client.lifecycle import ProfileRuntimeCoordinator, ProfileSwitchResult
from metor.client.stream import BufferedIpcEventReader
from metor.client.frontends import (
    FRONTEND_ENTRY_POINT_GROUP,
    FRONTEND_LAUNCH_CONTRACT_VERSION,
    FrontendDescriptor,
    LoadedFrontend,
    FrontendEntry,
    FrontendLaunchContext,
    FrontendLaunchError,
    discover_frontends,
    invoke_frontend,
    load_frontend,
    launch_frontend,
)

__all__ = [
    'AuthProvider',
    'BufferedIpcEventReader',
    'IpcAuthExchange',
    'IpcAuthResult',
    'IpcClient',
    'IpcClientError',
    'IpcDisconnectedError',
    'IpcRequestLimitError',
    'IpcSendError',
    'IpcTimeoutError',
    'FRONTEND_ENTRY_POINT_GROUP',
    'FRONTEND_LAUNCH_CONTRACT_VERSION',
    'FrontendDescriptor',
    'LoadedFrontend',
    'FrontendEntry',
    'FrontendLaunchContext',
    'FrontendLaunchError',
    'ContactQrError',
    'ContactQrPayload',
    'ContactQrValidationResult',
    'MetorClient',
    'ProfileRuntimeCoordinator',
    'ProfileSwitchResult',
    'build_session_auth_proof',
    'build_session_auth_proof_from_key',
    'build_pin_unlock_proof',
    'create_pin_verifier',
    'derive_pin_verifier',
    'derive_session_auth_proof_key',
    'extract_session_auth_prompt',
    'discover_frontends',
    'invoke_frontend',
    'load_frontend',
    'launch_frontend',
    'parse_endpoint',
    'validate_contact_qr',
]
