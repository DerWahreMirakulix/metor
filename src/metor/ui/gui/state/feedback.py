"""One volatile, expiring action result independent of persistent domain status."""

from dataclasses import dataclass
from time import monotonic

from metor.ui.gui.constants import GuiLimits


@dataclass
class ActionFeedback:
    """Keeps only the latest local result and never creates notification history."""

    text: str = ''
    revision: int = 0
    expires_at: float = 0

    def publish(self, text: str, *, now: float | None = None) -> None:
        """Replaces the current result, including a repeated deliberate action.

        Args:
            text: Locally formatted, privacy-permitted action result.
            now: Optional monotonic clock value for deterministic verification.
        """
        self.revision += 1
        self.text = text
        self.expires_at = (
            (monotonic() if now is None else now) + GuiLimits.FEEDBACK_SECONDS
            if text
            else 0
        )

    def visible(self, *, now: float | None = None) -> str:
        """Returns the current result only while its display interval remains open.

        Args:
            now: Optional monotonic clock value.
        Returns:
            str: Current result or an empty string after dismissal or expiry.
        """
        return (
            self.text if (monotonic() if now is None else now) < self.expires_at else ''
        )

    def clear(self) -> None:
        """Revokes feedback on dismissal, navigation, or a privacy transition."""
        self.publish('')
