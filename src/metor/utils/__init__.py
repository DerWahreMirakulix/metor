"""
Package initializer for the Utils layer.
Provides a unified API for constants, file locking, process management, and security helpers.
"""

from metor.utils.constants import Constants
from metor.utils.auth import (
    build_session_auth_proof,
    build_session_auth_proof_from_key,
    create_session_auth_challenge,
    derive_session_auth_proof_key,
    verify_session_auth_proof,
)
from metor.utils.lock import FileLock
from metor.utils.process import ProcessManager
from metor.utils.caster import TypeCaster
from metor.utils.validators import validate_json_file
from metor.utils.network import (
    clean_onion,
    decode_tor_v3_onion_public_key,
    ensure_onion_format,
)
from metor.utils.security import secure_shred_file

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
    'secure_shred_file',
    'verify_session_auth_proof',
]
