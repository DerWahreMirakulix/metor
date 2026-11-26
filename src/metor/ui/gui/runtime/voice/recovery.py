"""Explicit accepted-prefix finalization recovery for one original capture owner."""

from typing import TYPE_CHECKING

from metor.client import MetorClient
from metor.core.api import (
    IpcEvent,
    ContentType,
    MessageStatusCode,
    RetainedMessageEntry,
    MessageDirectionCode,
    RetainedMessagesEvent,
    VoiceCancelledEvent,
    VoiceFinalizedEvent,
)
from metor.ui.gui.platform.audio import PcmVoice
from metor.ui.gui.state.mailbox import Update

# Local Package Imports
from .press import CaptureBinding, PressPhase
from .models import VoiceReview

if TYPE_CHECKING:
    from .controller import VoiceController


class CaptureRecovery:
    """Rechecks exact Core state before a single explicitly requested finalization."""

    def __init__(self, voice: 'VoiceController') -> None:
        """Keeps recovery in the original volatile recording subsystem.

        Args:
            voice: Current activation's capture coordinator.
        Returns:
            None
        """
        self.voice = voice
        self.pending: CaptureBinding | None = None
        self._claiming = False

    def retry(self, binding: CaptureBinding) -> bool:
        """Recovers only the failed capture shown by the initiating control.

        Args:
            binding: Immutable original recording identity, including its activation.
        Returns:
            bool: Whether one explicit recovery operation was admitted.
        """
        voice, controller = self.voice, self.voice.controller
        client, owner = controller.client, controller.voice_owner.token
        if (
            controller.state.covered
            or client is None
            or owner is None
            or self.pending is not None
            or voice.running
            or voice.press.phase is not PressPhase.FAILED
            or voice.press.binding != binding
            or binding.generation != controller.state.generation
        ):
            return False
        if not controller.submit(
            'capture:recover:' + binding.msg_id,
            lambda: self._recover(client, owner, binding),
        ):
            return False
        self.pending = binding
        controller.state.status = 'Checking accepted recording before finalizing…'
        return True

    def claim(self, item: RetainedMessageEntry) -> bool:
        """Explicitly reclaims one interrupted producer into review without publishing.

        Args:
            item: Exact publicly advertised orphan draft shown by this control.
        Returns:
            bool: Whether a safe same-profile owner claim was admitted.
        """
        voice, controller = self.voice, self.voice.controller
        state, client, owner = (
            controller.state,
            controller.client,
            controller.voice_owner.token,
        )
        snapshot = state.snapshot
        if (
            state.covered
            or snapshot is None
            or not snapshot.profile_instance_id
            or not snapshot.epoch
            or client is None
            or owner is None
            or self.pending is not None
            or voice.running
            or voice.press.active
            or item.onion in voice.reviews
            or item.direction is not MessageDirectionCode.OUT
            or item.status is not MessageStatusCode.DRAFT
            or item.content_type is not ContentType.VOICE
            or not item.producer_interrupted
            or not item.can_retry_finalization
        ):
            return False
        binding = CaptureBinding(
            snapshot.profile_instance_id or '',
            snapshot.epoch or '',
            state.generation,
            item.onion,
            item.delivery,
            item.msg_id,
            item.context_generation,
        )
        if not controller.submit(
            'capture:claim:' + binding.msg_id,
            lambda: client.finalize_voice(
                binding.msg_id, PcmVoice.duration_ms(item.size_bytes), owner_token=owner
            ),
        ):
            return False
        self.pending = binding
        self._claiming = True
        state.status = 'Recovering the unsent recording for review…'
        return True

    @staticmethod
    def _recover(
        client: MetorClient, owner: str, binding: CaptureBinding
    ) -> IpcEvent | None:
        """Reads before mutation, then only reads after an uncertain result.

        Args:
            client: Captured authenticated producer connection.
            owner: Captured connection-bound producer lease.
            binding: Original recording; navigation cannot retarget it.
        Returns:
            IpcEvent | None: Actual completion, retained state, or unconfirmed result.
        """

        def lookup() -> RetainedMessagesEvent | None:
            """Reads only this owner's exact outbound recording metadata.

            Args:
                None
            Returns:
                RetainedMessagesEvent | None: Authoritative bounded exact lookup.
            """
            return client.list_retained_messages(
                target=binding.peer,
                direction=MessageDirectionCode.OUT,
                msg_id=binding.msg_id,
                owner_token=owner,
            )

        page = lookup()
        if page is None:
            return None
        item = next(
            (
                row
                for row in page.messages
                if row.onion == binding.peer
                and row.msg_id == binding.msg_id
                and row.direction is MessageDirectionCode.OUT
            ),
            None,
        )
        if item is None or item.finalized:
            return page
        try:
            result: IpcEvent | None = (
                client.cancel_voice(binding.peer, binding.msg_id, owner_token=owner)
                if item.size_bytes == 0
                else client.finalize_voice(
                    binding.msg_id,
                    PcmVoice.duration_ms(item.size_bytes),
                    owner_token=owner,
                )
            )
            if isinstance(result, (VoiceFinalizedEvent, VoiceCancelledEvent)):
                return result
        except Exception:
            # A lost response permits only a read; accepted audio is never resent.
            pass
        return lookup()

    def install(self, update: Update) -> bool:
        """Installs exact completion through the ordinary capture state machine.

        Args:
            update: Current-generation bounded worker completion.
        Returns:
            bool: Whether this recovery owner handled the update.
        """
        if not update.operation.startswith(('capture:recover:', 'capture:claim:')):
            return False
        binding = self.pending
        if binding is None or not update.operation.endswith(':' + binding.msg_id):
            return True
        self.pending = None
        if self._claiming:
            self._claiming = False
            event = update.event
            if (
                isinstance(event, VoiceFinalizedEvent)
                and event.msg_id == binding.msg_id
                and event.onion == binding.peer
                and event.delivery is binding.delivery
                and event.size_bytes > 0
            ):
                self.voice.reviews[binding.peer] = VoiceReview(
                    binding, event.size_bytes, event.duration_ms
                )
                self.voice.controller.state.status = (
                    'Recovered recording ready to review'
                )
                self.voice.controller.inventory.reset()
            else:
                self.voice.controller.state.status = (
                    'Recording recovery was not confirmed'
                )
            return True
        if self.voice.press.binding != binding:
            return True
        event = update.event
        cancelled = (
            isinstance(event, VoiceCancelledEvent)
            and event.msg_id == binding.msg_id
            and event.onion == binding.peer
        )
        self.voice.install(
            Update(
                update.generation,
                ('voice-empty:' if cancelled else 'voice-finished:') + binding.msg_id,
                event,
                'No audio was captured' if cancelled else '',
            )
        )
        if self.voice.press.phase is PressPhase.FAILED:
            self.voice.controller.state.status = (
                'Recording remains unconfirmed. Retry finalization when available.'
            )
        return True
