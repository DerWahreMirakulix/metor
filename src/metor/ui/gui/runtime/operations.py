"""Bounded foreground and read lanes with exact result ownership and read fences."""

from collections.abc import Callable
from dataclasses import dataclass, replace
import threading

from metor.client import (
    FrontendBootstrapError,
    IpcDisconnectedError,
    IpcTimeoutError,
    MetorRequestRejectedError,
)
from metor.core.api import IpcEvent
from metor.ui.gui.launcher import report_worker_failure
from metor.ui.gui.state.mailbox import Mailbox, Update


@dataclass
class _Owner:
    """One admitted operation, retained until its exact completion is consumed."""

    token: int
    generation: int
    thread: threading.Thread


class OperationScheduler:
    """Runs one mutation alongside one read without creating an unbounded queue.

    Read work never prevents an explicit mutation from starting. New reads wait
    while a mutation is pending; results captured before that mutation cannot
    replace the subsequently confirmed projection. SDK requests retain their
    independent request leases and response correlation on both lanes.
    """

    def __init__(self, mailbox: Mailbox, *, debug: bool) -> None:
        """Creates two empty operation lanes and an activation-independent fence.

        Args:
            mailbox: Bounded worker-to-GUI result owner.
            debug: Whether contained worker failures are reported diagnostically.
        Returns:
            None
        """
        self._mailbox = mailbox
        self._debug = debug
        self._foreground: _Owner | None = None
        self._read: _Owner | None = None
        self._serial = 0
        self._read_epoch = 0
        self._read_turn = 0

    def poll_reads(self, readers: tuple[Callable[[], bool | None], ...]) -> bool:
        """Rotates generic read admission after a successful claim, while polling every owner.

        Args:
            readers: Fixed ordered owners, captured freshly from the current activation.
        Returns:
            bool: Whether any owner reported a presentation or lifecycle change.
        """
        if not readers:
            return False
        changed = False
        start = self._read_turn % len(readers)
        for offset in range(len(readers)):
            index = (start + offset) % len(readers)
            previous = self._read
            changed = bool(readers[index]()) or changed
            if previous is None and self._read is not None:
                self._read_turn = (index + 1) % len(readers)
        return changed

    def invalidate_reads(self) -> None:
        """Invalidates older projections after mutations without discarding exact outcomes.

        Args:
            None
        Returns:
            None
        """
        self._read_epoch += 1

    def read_is_current(self, update: Update) -> bool:
        """Checks a stamped projection while retaining unsolicited typed content events.

        Args:
            update: Result from the already generation-checked GUI mailbox.
        Returns:
            bool: Whether its projection was captured after the latest mutation.
        """
        return update.read_epoch is None or update.read_epoch == self._read_epoch

    def foreground_pending(self, generation: int) -> bool:
        """Reports exact foreground ownership for the current activation.

        Args:
            generation: Current GUI activation generation.
        Returns:
            bool: Whether its operation still awaits completion installation.
        """
        return (
            self._foreground is not None and self._foreground.generation == generation
        )

    def admit(
        self,
        generation: int,
        operation: str,
        work: Callable[[], IpcEvent | None],
        *,
        background: bool,
    ) -> threading.Thread | None:
        """Starts one independently correlated request without deferring a mutation.

        Args:
            generation: Activation captured before scheduling the work.
            operation: Exact frontend operation identity.
            work: Captured SDK or public host operation.
            background: Whether this operation only reads projection state.
        Returns:
            Thread | None: The admitted bounded worker, or no admission.
        """
        # Abandoned workers keep their lane until they actually finish. This
        # bounds threads even across repeated profile closure and activation.
        if (
            self._foreground is not None
            and self._foreground.generation != generation
            and not self._foreground.thread.is_alive()
        ):
            self._foreground = None
        if (
            self._read is not None
            and self._read.generation != generation
            and not self._read.thread.is_alive()
        ):
            self._read = None
        if self._foreground is not None or (background and self._read is not None):
            return None
        self._serial += 1
        token = self._serial
        if not background:
            self.invalidate_reads()
        read_epoch = self._read_epoch if background else None

        def run() -> None:
            """Contains worker errors and publishes one exact completion record."""
            update = self._execute(generation, operation, work)
            self._mailbox.put(
                replace(
                    update,
                    background=background,
                    worker_token=token,
                    read_epoch=read_epoch,
                )
            )

        thread = threading.Thread(
            target=run,
            name='metor-gui-read' if background else 'metor-gui-operation',
            daemon=True,
        )
        owner = _Owner(token, generation, thread)
        if background:
            self._read = owner
        else:
            self._foreground = owner
        thread.start()
        return thread

    def complete(self, update: Update) -> bool:
        """Releases only the matching lane; a read cannot finish a foreground action.

        Args:
            update: Completion carrying the immutable worker owner token.
        Returns:
            bool: Whether the foreground operation completed.
        """
        if update.worker_token is None:
            return False
        owner = self._read if update.background else self._foreground
        if (
            owner is None
            or owner.token != update.worker_token
            or owner.generation != update.generation
        ):
            return False
        if update.background:
            self._read = None
            return False
        self._foreground = None
        self.invalidate_reads()
        return True

    def _execute(
        self, generation: int, operation: str, work: Callable[[], IpcEvent | None]
    ) -> Update:
        """Maps one bounded worker result or failure to a typed GUI update.

        Args:
            generation: Original activation generation.
            operation: Original frontend action identity.
            work: Captured SDK or public host operation.
        Returns:
            Update: One result; uncertain mutations retain their existing status.
        """
        try:
            event = work()
            if event is None and (
                operation == 'bootstrap' or operation.startswith('A')
            ):
                return Update(
                    generation,
                    operation,
                    status=(
                        'Profile opening was cancelled or rejected.'
                        if operation == 'bootstrap'
                        else 'Operation could not be confirmed'
                    ),
                )
            return Update(generation, operation, event)
        except MetorRequestRejectedError as exc:
            return Update(
                generation, operation, exc.event, status='Operation was rejected'
            )
        except FrontendBootstrapError as exc:
            return Update(generation, operation, status=str(exc))
        except IpcTimeoutError:
            return Update(
                generation,
                operation,
                status='Connection timed out. Retry opening the profile.',
            )
        except IpcDisconnectedError:
            return Update(
                generation,
                operation,
                status='Connection lost. Retry opening the profile.',
            )
        except Exception as exc:  # noqa: BLE001 - contain worker failures
            if self._debug:
                report_worker_failure(exc)
            return Update(
                generation,
                operation,
                status=(
                    'Profile opening failed. Retry or choose another profile.'
                    if operation == 'bootstrap'
                    else 'Operation could not be confirmed'
                ),
            )
