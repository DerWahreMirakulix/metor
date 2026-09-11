"""Public launcher entry point for the independently installed Terminal UI."""

from metor.client import (
    FRONTEND_LAUNCH_CONTRACT_VERSION,
    FrontendLaunchContext,
    FrontendLaunchError,
)
from metor.data import ProfileManager
from metor.ui.terminal.chat import Chat


def launch(context: FrontendLaunchContext) -> int:
    """Starts the Terminal frontend from the public versioned launch context.

    Args:
        context (FrontendLaunchContext): Base-CLI bootstrap context.

    Raises:
        FrontendLaunchError: If the launcher contract is incompatible.

    Returns:
        int: Process exit status.
    """
    if context.contract_version != FRONTEND_LAUNCH_CONTRACT_VERSION:
        raise FrontendLaunchError(
            'The installed Terminal frontend uses an incompatible launch contract.'
        )
    profile = ProfileManager(context.profile)
    chat = Chat(
        profile,
        prefilled_session_auth_password=context.session_auth_secret,
    )
    chat.run()
    return 0


# Entry-point metadata cannot express the typed contract generation. Publishing
# it on the selected callable allows the base launcher to reject incompatible UI
# packages before it performs profile or daemon bootstrap side effects.
setattr(launch, 'contract_version', FRONTEND_LAUNCH_CONTRACT_VERSION)
