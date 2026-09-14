"""Explicit new-DROP resend with one retained identity through unknown results."""

import secrets
from typing import TYPE_CHECKING

from metor.core.api import (
    Delivery,
    DropQueuedEvent,
    GetMessageOutcomeCommand,
    MessageDirectionCode,
    MessageOutcomeEvent,
    MessageStatusCode,
    VoiceCancelledEvent,
    VoiceCommittedEvent,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.state.mailbox import Update

# Local Package Imports
from .source import available_source
from .worker import ResendWorker

if TYPE_CHECKING:
    from ..controller import GuiController


class ResendActions:
    """Keeps exactly one new-message intent; original LIVE identity and delivery remain unchanged."""

    def __init__(self, controller: 'GuiController') -> None:
        """Creates an inert profile-scoped resend owner with no source or credentials.

        Args:
            controller: Current public SDK and cache owner.
        Returns:
            None
        """
        self.controller = controller
        self.current: ResendWorker | None = None
        self.pending = False
        self.state = ''
        self.status = ''
        self.revision = 0
        self._check_needed = False

    def available(self, peer: str, msg_id: str) -> bool:
        """Checks exact retained source metadata without reading files or refetching erased media.

        Args:
            peer: Original own LIVE peer.
            msg_id: Original delivered LIVE identity.
        Returns:
            bool: Whether a new explicit resend can currently be admitted.
        """
        return (
            not self.controller.simulator
            and self.current is None
            and available_source(self.controller, peer, msg_id) is not None
        )

    def start(self, peer: str, msg_id: str) -> bool:
        """Captures a complete permitted source and allocates one fresh DROP identity.

        Args:
            peer: Exact source peer and destination for the new DROP.
            msg_id: Original LIVE source, never the new message identity.
        Returns:
            bool: Whether one explicit resend was admitted.
        """
        controller, client = self.controller, self.controller.client
        if (
            controller.simulator
            or self.current is not None
            or client is None
            or controller.state.covered
            or controller.voice.press.active
            or controller.voice.running
        ):
            return False
        source = available_source(controller, peer, msg_id)
        if source is None:
            controller.state.status = 'Complete source no longer available'
            return False
        owner = controller.voice_owner.token
        if source.text is None and (
            owner is None
            or 'disposable_voice_owner' not in controller.state.capabilities
        ):
            controller.state.status = 'Voice resend is unavailable'
            return False
        worker = ResendWorker(
            client,
            source,
            secrets.token_hex(GuiLimits.MESSAGE_ID_BYTES),
            owner,
            controller.playback.cache,
        )
        if not controller.submit('resend:create:' + worker.msg_id, worker.run):
            return False
        self.current, self.pending = worker, True
        self.state, self.status = 'copying', 'Queueing new Drop…'
        controller.state.status = self.status
        self.revision += 1
        return True

    def check(self) -> bool:
        """Reads only the new identity's receipt; absence is never proof of non-delivery.

        Args:
            None
        Returns:
            bool: Whether one exact readback was admitted.
        """
        worker = self.current
        controller = self.controller
        if (
            controller.simulator
            or worker is None
            or self.pending
            or controller.state.covered
            or 'message_outcome' not in controller.state.capabilities
        ):
            return False
        return controller.submit(
            'resend:check:' + worker.msg_id,
            lambda: worker.client.request(
                GetMessageOutcomeCommand(
                    worker.source.target.peer, worker.msg_id, MessageDirectionCode.OUT
                ),
                MessageOutcomeEvent,
            ),
        )

    def discard(self) -> bool:
        """Cancels only a read-confirmed uncommitted new Voice copy, never its original source.

        Args:
            None
        Returns:
            bool: Whether one explicit exact-owner cancellation was admitted.
        """
        worker = self.current
        controller = self.controller
        if (
            controller.simulator
            or worker is None
            or worker.source.text is not None
            or self.pending
            or self.state != 'draft'
            or controller.state.covered
        ):
            return False
        admitted = controller.submit(
            'resend:discard:' + worker.msg_id,
            lambda: worker.client.cancel_voice(
                worker.source.target.peer, worker.msg_id, owner_token=worker.owner
            ),
        )
        if admitted:
            self.pending = True
        return admitted

    def cancel(self) -> None:
        """Stops copying before the next request without assuming an in-flight request was rejected.

        Args:
            None
        Returns:
            None
        """
        if self.current is not None:
            self.current.cancelled.set()

    def poll(self) -> None:
        """Schedules one coalesced read after uncertain creation; failed reads need explicit retry.

        Args:
            None
        Returns:
            None
        """
        if self._check_needed and self.check():
            self._check_needed = False

    def install(self, update: Update) -> bool:
        """Reconciles only the new exact DROP identity and keeps incomplete copies unsent.

        Args:
            update: Generation-validated result from the original captured client.
        Returns:
            bool: Whether this owner consumed the update.
        """
        if not update.operation.startswith('resend:'):
            return False
        worker = self.current
        if worker is None or not update.operation.endswith(':' + worker.msg_id):
            return True
        self.pending = False
        event, peer = update.event, worker.source.target.peer
        kind = update.operation.split(':', 2)[1]
        positive = (
            isinstance(event, DropQueuedEvent)
            and worker.source.text is not None
            and kind == 'create'
            and event.onion in {None, peer}
        ) or (
            isinstance(event, VoiceCommittedEvent)
            and event.msg_id == worker.msg_id
            and event.onion == peer
        )
        discarded = (
            isinstance(event, VoiceCancelledEvent)
            and kind == 'discard'
            and event.msg_id == worker.msg_id
            and event.onion == peer
        )
        if (
            isinstance(event, MessageOutcomeEvent)
            and event.onion == peer
            and event.msg_id == worker.msg_id
            and event.direction is MessageDirectionCode.OUT
            and event.delivery is Delivery.DROP
        ):
            positive = event.status in {
                MessageStatusCode.PENDING,
                MessageStatusCode.DELIVERED,
                MessageStatusCode.READ,
            }
            if event.status is MessageStatusCode.DRAFT and worker.source.text is None:
                self.state = 'draft'
                self.status = 'The new recording is still unsent. Discard the incomplete resend before trying again.'
                self.revision += 1
                if not self.controller.state.covered:
                    self.controller.state.status = self.status
                return True
        if positive or discarded:
            self.current = None
            self.state = 'queued' if positive else 'discarded'
            self.status = 'New Drop queued' if positive else 'Unsent resend discarded'
            self._check_needed = False
            self.controller.refresh_state()
        elif kind == 'create' and (
            worker.phase == 'source' or worker.rejected and not worker.begun
        ):
            self.current = None
            self.state = 'rejected'
            self.status = (
                'Complete source no longer available'
                if worker.phase == 'source'
                else 'Could not queue the new Drop'
            )
        else:
            self.state = 'unknown'
            self.status = 'New Drop outcome is unconfirmed. Check its result before another resend.'
            if kind != 'check':
                self._check_needed = True
        if not self.controller.state.covered:
            self.controller.state.status = self.status
        self.revision += 1
        return True

    def clear(self) -> None:
        """Releases only volatile intent; Core still owns any accepted new message or staging.

        Args:
            None
        Returns:
            None
        """
        self.cancel()
        self.current = None
        self.pending = False
        self._check_needed = False
        self.state = self.status = ''
        self.revision += 1
