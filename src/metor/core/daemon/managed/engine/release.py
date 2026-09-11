"""Independent, outcome-aware release of security-sensitive runtime resources."""

from dataclasses import dataclass
from typing import Callable, Iterable


@dataclass(frozen=True)
class RuntimeReleaseResult:
    """Known local cleanup outcomes; successful calls cannot prove physical erasure."""

    attempted: tuple[str, ...]
    failed: tuple[str, ...]

    @property
    def succeeded(self) -> bool:
        """Reports whether every attempted release returned successfully."""
        return not self.failed


def release_resources(
    steps: Iterable[tuple[str, Callable[[], object]]],
) -> RuntimeReleaseResult:
    """Attempts every release even after an earlier failure, retaining only safe phases.

    Args:
        steps (Iterable[tuple[str, Callable[[], object]]]): Ordered release actions.

    Returns:
        RuntimeReleaseResult: Exact attempted and failed phase names.
    """
    attempted: list[str] = []
    failed: list[str] = []
    for phase, action in steps:
        attempted.append(phase)
        try:
            if action() is False:
                failed.append(phase)
        except Exception:
            failed.append(phase)
    return RuntimeReleaseResult(tuple(attempted), tuple(failed))
