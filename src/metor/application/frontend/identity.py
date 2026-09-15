"""Offline address operations delegated to existing Core owners with exact local host eligibility."""

from metor.client import FrontendProfileAddressRequest, FrontendProfileOperationResult
from metor.core.api import (
    AddressCurrentEvent,
    AddressGeneratedEvent,
    create_event,
)
from metor.core.daemon import InvalidMasterPasswordError, verify_master_password
from metor.core.key import KeyManager
from metor.core.tor import TorManager
from metor.data import ProfileManager, Settings


def profile_address(
    request: FrontendProfileAddressRequest, password: str | None
) -> FrontendProfileOperationResult:
    """Uses actual Core preconditions/effects without stopping shared runtimes or inventing rotation.

    Args:
        request: Validated exact local profile operation.
        password: One-use full target-profile password, never a quick-unlock PIN.
    Returns:
        FrontendProfileOperationResult: Existing Core outcome or safe eligibility refusal.
    """
    request.__post_init__()
    pm = ProfileManager(request.profile)
    if not pm.exists() or pm.is_remote():
        return FrontendProfileOperationResult(
            False, 'local_profile_required', request.profile
        )
    if pm.is_daemon_running():
        return FrontendProfileOperationResult(
            False, 'address_cant_generate_running', request.profile
        )
    Settings.validate_integrity()
    pm.validate_integrity()
    manager = KeyManager(pm, password)
    try:
        if pm.supports_password_auth():
            try:
                verify_master_password(manager)
            except InvalidMasterPasswordError:
                return FrontendProfileOperationResult(
                    False, 'invalid_password', request.profile
                )
        tor = TorManager(pm, manager)
        _success, event_type, params = (
            tor.generate_address() if request.generate else tor.get_address()
        )
        event = create_event(event_type, params)
        success = isinstance(event, (AddressCurrentEvent, AddressGeneratedEvent))
        return FrontendProfileOperationResult(
            success,
            event.event_type.value,
            request.profile,
            event.onion
            if isinstance(event, (AddressCurrentEvent, AddressGeneratedEvent))
            else None,
        )
    finally:
        manager.clear_sensitive_state()
