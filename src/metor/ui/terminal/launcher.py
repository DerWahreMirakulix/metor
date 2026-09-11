"""Public launcher entry point for the independently installed Terminal UI."""

from metor.client import (
    FRONTEND_LAUNCH_CONTRACT_VERSION,
    FrontendBootstrapError,
    FrontendInteractions,
    FrontendLaunchContext,
    FrontendLaunchError,
)
from metor.ui.terminal import (
    PromptAbortedError,
    PromptOutputSpacer,
    Theme,
    prompt_hidden,
    prompt_text,
)
from metor.data import ProfileManager
from metor.ui.terminal.chat import Chat


class _TerminalInteractions(FrontendInteractions):
    """Terminal adapter for host-owned bootstrap decisions."""

    def __init__(self) -> None:
        """Initializes Terminal-specific bootstrap output spacing.

        Args:
            None

        Returns:
            None
        """
        self._spacer = PromptOutputSpacer()

    def confirm_daemon_start(self) -> bool | None:
        """Prompts for optional local daemon startup.

        Args:
            None

        Returns:
            bool | None: Decision, or None after prompt cancellation.
        """
        try:
            value = prompt_text("Type 'yes' to start the local daemon: ")
            self._spacer.mark_prompt()
        except PromptAbortedError:
            return None
        return value.strip().lower() == 'yes'

    def request_session_auth_secret(self) -> str | None:
        """Prompts for a startup-only session authentication secret.

        Args:
            None

        Returns:
            str | None: Secret text, or None after cancellation.
        """
        try:
            value = prompt_hidden(
                f'{Theme.GREEN}Enter Session Auth Password: {Theme.RESET}'
            )
            self._spacer.mark_prompt()
        except PromptAbortedError:
            return None
        return value or None

    def show_status(self, message: str) -> None:
        """Prints one host-owned non-secret bootstrap status.

        Args:
            message (str): Safe status text.

        Returns:
            None
        """
        print(self._spacer.format(message))


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
    interactions = _TerminalInteractions()
    try:
        bootstrap = context.host.bootstrap(interactions)
    except FrontendBootstrapError as exc:
        if str(exc):
            print(interactions._spacer.format(str(exc)))
        return exc.exit_code
    profile = ProfileManager(bootstrap.profile)
    chat = Chat(
        profile,
        startup_session_auth_provider=bootstrap.session_auth.take,
    )
    chat.run()
    return 0


# Entry-point metadata cannot express the typed contract generation. Publishing
# it on the selected callable allows the base launcher to reject incompatible UI
# packages before it performs profile or daemon bootstrap side effects.
setattr(launch, 'contract_version', FRONTEND_LAUNCH_CONTRACT_VERSION)
