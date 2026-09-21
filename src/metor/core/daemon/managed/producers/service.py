"""Connection-bound Voice admission and revocation over durable producer claims."""

import secrets
import socket
from typing import Callable

from metor.core.api import (
    AppendVoiceChunkCommand,
    BeginVoiceCommand,
    CancelVoiceCommand,
    CommitVoiceCommand,
    Delivery,
    FinalizeVoiceCommand,
    GetVoiceChunkCommand,
    IpcCommand,
    IpcEvent,
    ListRetainedMessagesCommand,
    MessageDirectionCode,
    MessageOperationReason,
    RegisterVoiceOwnerCommand,
    ReleaseVoiceOwnerCommand,
    VoiceCancelledEvent,
    VoiceOperationRejectedEvent,
    VoiceOwnerRegisteredEvent,
    VoiceOwnerRejectedEvent,
    VoiceOwnerReleasedEvent,
    request_context,
)
from metor.utils import Constants

# Local Package Imports
from .cleanup import ProducerCleanup


class VoiceProducerService:
    """Owns leases under the daemon's domain operation lock, never GUI memory."""

    def __init__(
        self,
        cleanup: ProducerCleanup,
        resolve: Callable[[str], str | None],
        send: Callable[[socket.socket, IpcEvent], None],
        purging: Callable[[], bool],
        context: Callable[[str, str], int | None] | None = None,
        current_context: Callable[[str], object | None] | None = None,
    ) -> None:
        """Binds one service to one unlocked profile runtime.

        Args:
            cleanup: Canonical cleanup and ownership transfer adapter.
            resolve: Core peer identity resolver.
            send: Request-scoped event sender.
            purging: Immediate irreversible-purge fence.
            context: Exact admitted LIVE recording generation.
            current_context: Currently active or recovering logical context.
        Returns:
            None
        """
        self._cleanup = cleanup
        self._resolve = resolve
        self._send = send
        self._purging = purging
        self._owners: dict[socket.socket, str] = {}
        self._context = context or (lambda _onion, _msg_id: None)
        self._current_context = current_context or (lambda _onion: None)
        self._contexts: dict[str, tuple[str, int]] = {}

    def before(self, cmd: IpcCommand, conn: socket.socket) -> bool:
        """Authorizes owned operations before existing command-family dispatch.

        Args:
            cmd: Already session-authorized typed command.
            conn: Actual requesting IPC connection, never a client assertion.
        Returns:
            bool: Whether the existing domain handler should continue.
        """
        if self._purging():
            return False
        repository = self._cleanup.repository
        if isinstance(cmd, RegisterVoiceOwnerCommand):
            if not cmd.disposable_drop or not repository.protected:
                self._send(conn, VoiceOwnerRejectedEvent())
            else:
                owner = self._owners.get(conn)
                if owner is None:
                    if len(self._owners) >= Constants.VOICE_OWNER_MAX_PROFILE_ITEMS:
                        self._send(conn, VoiceOwnerRejectedEvent())
                        return False
                    owner = secrets.token_hex(Constants.VOICE_OWNER_TOKEN_BYTES)
                    self._owners[conn] = owner
                self._send(conn, VoiceOwnerRegisteredEvent(owner))
            return False
        if isinstance(cmd, ReleaseVoiceOwnerCommand):
            if self._owners.get(conn) != cmd.owner_token or not cmd.owner_token:
                self._send(conn, VoiceOwnerRejectedEvent())
            else:
                self.disconnect(conn)
                pending = any(
                    item.owner_token == cmd.owner_token for item in repository.items()
                )
                self._send(conn, VoiceOwnerReleasedEvent(pending))
            return False
        if isinstance(cmd, ListRetainedMessagesCommand):
            if cmd.owner_token is not None and (
                not cmd.owner_token or self._owners.get(conn) != cmd.owner_token
            ):
                self._send(conn, VoiceOwnerRejectedEvent())
                return False
            return True
        if not isinstance(
            cmd,
            (
                BeginVoiceCommand,
                AppendVoiceChunkCommand,
                FinalizeVoiceCommand,
                CommitVoiceCommand,
                CancelVoiceCommand,
                GetVoiceChunkCommand,
            ),
        ):
            return True
        if isinstance(cmd, GetVoiceChunkCommand) and (
            cmd.direction is MessageDirectionCode.IN
        ):
            return True
        item = repository.get(cmd.msg_id)
        owner = cmd.owner_token
        authorized = (
            owner is not None and bool(owner) and self._owners.get(conn) == owner
        )
        if isinstance(cmd, BeginVoiceCommand) and owner is not None:
            onion = self._resolve(cmd.target)
            if authorized and onion is not None and item is None:
                if repository.claim(owner, onion, cmd.msg_id, cmd.delivery):
                    return True
            self._reject(conn, cmd.msg_id)
            return False
        if item is None:
            if owner is None:
                return True
            self._reject(conn, cmd.msg_id)
            return False
        if (
            isinstance(cmd, FinalizeVoiceCommand)
            and item.delivery is Delivery.LIVE
            and item.interrupted
            and (
                (authorized and item.owner_token == owner)
                or (owner is None and item.owner_token not in self._owners.values())
            )
        ):
            try:
                with request_context(None):
                    reclaimed = self._cleanup.reclaim(item)
                if not reclaimed:
                    self._reject(
                        conn,
                        cmd.msg_id,
                        MessageOperationReason.PERSISTENCE_FAILED,
                    )
                else:
                    self._send(conn, self._cleanup.finalization_result(item))
            except Exception:
                self._reject(
                    conn, cmd.msg_id, MessageOperationReason.PERSISTENCE_FAILED
                )
            return False
        if not authorized or item.owner_token != owner:
            self._reject(conn, cmd.msg_id)
            return False
        if item.interrupted and isinstance(cmd, AppendVoiceChunkCommand):
            self._reject(conn, cmd.msg_id)
            return False
        if isinstance(cmd, FinalizeVoiceCommand) and item.delivery is Delivery.LIVE:
            self._cleanup.repository.mark_interrupted(item)
        if item.cleanup_payload is not None and not isinstance(cmd, CancelVoiceCommand):
            self._reject(conn, cmd.msg_id, MessageOperationReason.PERSISTENCE_FAILED)
            return False
        if isinstance(
            cmd, (CommitVoiceCommand, CancelVoiceCommand, GetVoiceChunkCommand)
        ):
            if self._resolve(cmd.target) != item.onion:
                self._reject(conn, cmd.msg_id)
                return False
        if isinstance(cmd, CancelVoiceCommand):
            if item.delivery is not Delivery.DROP or self._cleanup.transferred(item):
                self._reject(conn, cmd.msg_id)
                return False
            try:
                success = self._cleanup.reclaim(item)
            except Exception:
                success = False
            if success:
                self._send(
                    conn,
                    VoiceCancelledEvent(
                        alias=item.onion, onion=item.onion, msg_id=item.msg_id
                    ),
                )
            else:
                self._reject(
                    conn, cmd.msg_id, MessageOperationReason.PERSISTENCE_FAILED
                )
            return False
        return True

    def after(self, cmd: IpcCommand) -> None:
        """Transfers claims only after canonical commit/finalization is visible.

        Args:
            cmd: Completed domain operation; its response may have been lost.
        Returns:
            None
        """
        if self._purging() or not isinstance(
            cmd, (BeginVoiceCommand, CommitVoiceCommand, FinalizeVoiceCommand)
        ):
            return
        item = self._cleanup.repository.get(cmd.msg_id)
        if item is not None:
            if isinstance(cmd, BeginVoiceCommand) and not self._cleanup.has_receipt(
                item
            ):
                self._cleanup.reclaim(item)
            elif self._cleanup.transferred(item):
                self._cleanup.release_transferred(item)
                self._contexts.pop(item.msg_id, None)
            elif isinstance(cmd, BeginVoiceCommand) and item.delivery is Delivery.LIVE:
                generation = self._context(item.onion, item.msg_id)
                if generation is not None:
                    self._contexts[item.msg_id] = item.owner_token, generation

    def disconnect(self, conn: socket.socket) -> None:
        """Revokes a confirmed lost connection before attempting durable cleanup.

        Args:
            conn: Exact connection whose producer lease is invalidated.
        Returns:
            None
        """
        self._owners.pop(conn, None)
        self.retry()

    def retry(self) -> bool:
        """Retries all orphan claims while preserving failures for later recovery.

        Args:
            None
        Returns:
            bool: Whether all currently orphaned claims were reconciled.
        """
        if self._purging():
            return False
        active = set(self._owners.values())
        completed = True
        try:
            items = self._cleanup.repository.items()
        except Exception:
            return False
        retained = {item.msg_id for item in items}
        for msg_id in tuple(self._contexts):
            if msg_id not in retained:
                self._contexts.pop(msg_id, None)
        for item in items:
            if self._purging():
                return False
            try:
                context = self._contexts.get(item.msg_id)
                context_ended = (
                    context is not None
                    and context[0] == item.owner_token
                    and self._current_context(item.onion) != context[1]
                )
                if (
                    not context_ended
                    and item.owner_token in active
                    and item.cleanup_payload is None
                    and not item.interrupted
                ):
                    if self._cleanup.transferred(item):
                        self._cleanup.release_transferred(item)
                    continue
                with request_context(None):
                    reclaimed = self._cleanup.reclaim(item)
                    if reclaimed:
                        self._contexts.pop(item.msg_id, None)
                    completed = reclaimed and completed
            except Exception:
                completed = False
        return completed

    def release_all(self) -> None:
        """Revokes all producers before normal profile resource release.

        Args:
            None
        Returns:
            None
        """
        self._owners.clear()
        if not self.retry():
            raise OSError('Voice producer cleanup remains pending')

    def _reject(
        self,
        conn: socket.socket,
        msg_id: str,
        reason: MessageOperationReason = MessageOperationReason.STALE_CAPTURE,
    ) -> None:
        """Returns a typed recording failure without exposing another owner.

        Args:
            conn: Requesting connection.
            msg_id: Submitted logical identity.
            reason: Content-free rejection classification.
        Returns:
            None
        """
        self._send(conn, VoiceOperationRejectedEvent(msg_id=msg_id, reason=reason))
