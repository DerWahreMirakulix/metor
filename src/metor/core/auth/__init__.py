"""Public deterministic proof primitives, independent of runtime authorization."""

from .pin import (
    PIN_PASSWORD_PREFIX,
    PIN_SALT_BYTES,
    PIN_VERIFIER_BYTES,
    build_pin_unlock_proof,
    create_pin_verifier,
    derive_pin_verifier,
)
from .session import (
    SESSION_AUTH_PASSWORD_PREFIX,
    build_session_auth_proof,
    build_session_auth_proof_from_key,
    create_session_auth_challenge,
    create_session_auth_salt,
    derive_session_auth_proof_key,
    verify_session_auth_proof,
)

__all__ = [
    'PIN_PASSWORD_PREFIX',
    'SESSION_AUTH_PASSWORD_PREFIX',
    'PIN_SALT_BYTES',
    'PIN_VERIFIER_BYTES',
    'build_pin_unlock_proof',
    'create_pin_verifier',
    'derive_pin_verifier',
    'build_session_auth_proof',
    'build_session_auth_proof_from_key',
    'create_session_auth_challenge',
    'create_session_auth_salt',
    'derive_session_auth_proof_key',
    'verify_session_auth_proof',
]
