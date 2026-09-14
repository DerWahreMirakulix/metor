"""Typed text-send admission and legacy acknowledgement-compatible IPC routing."""

import socket
from typing import Callable

from metor.core.api import (
    Delivery,
    EventType,
    IpcEvent,
    SendMessageCommand,
    TextContent,
    ContentType,
    create_event,
)
from metor.core.daemon.managed.network import NetworkManager
from metor.core.daemon.managed.outbox import OutboxWorker
from metor.data import (
    ContactManager,
    HistoryManager,
    MessageManager,
    SettingKey,
    MessageDirection,
    MessageStatus,
    HistoryActor,
    HistoryEvent,
)
from metor.data.profile import Config


class TextCommandHandler:
    """Owns local text command results while transport owns delivery and receipts."""

    def __init__(
        self,
        contacts: ContactManager,
        history: HistoryManager,
        messages: MessageManager,
        network: NetworkManager,
        outbox: OutboxWorker,
        config: Config,
        is_self_target: Callable[[str], bool],
        send_event: Callable[[socket.socket, IpcEvent], None],
    ) -> None:
        """Binds the accepted runtime collaborators without taking their ownership.

        Args:
            contacts: Canonical target resolver.
            history: Core activity-history owner.
            messages: Durable receipt/admission owner.
            network: LIVE routing owner.
            outbox: DROP request-correlation owner.
            config: Core delivery policy.
            is_self_target: Current profile self-target guard.
            send_event: Request-correlated IPC result sender.
        Returns:
            None
        """
        self._cm, self._hm, self._mm = contacts, history, messages
        self._network, self._outbox, self._config = network, outbox, config
        self._is_self_target, self._send_event = is_self_target, send_event

    def handle(self, cmd: SendMessageCommand, conn: socket.socket) -> None:
        """Routes only typed text through existing durable admission paths.

        Args:
            cmd: Explicit text command with optional local-admission result.
            conn: Authorized requesting IPC session.
        Returns:
            None
        """
        if not isinstance(cmd.content, TextContent):
            return
        if cmd.delivery is Delivery.LIVE:
            if cmd.local_acceptance:
                if self._cm.resolve_target(cmd.target) is None:
                    self._send_event(
                        conn,
                        create_event(EventType.INVALID_TARGET, {'target': cmd.target}),
                    )
                    return

                def local_result(event: IpcEvent) -> None:
                    """Returns this request's local outcome before peer IO.

                    Args:
                        event: Durable admission or definite resource rejection.
                    Returns:
                        None
                    """
                    self._send_event(conn, event)

                self._network.send_message(
                    cmd.target, cmd.content.text, cmd.msg_id, local_result
                )
            else:
                self._network.send_message(cmd.target, cmd.content.text, cmd.msg_id)

        else:
            if not self._config.get_bool(SettingKey.ALLOW_DROPS):
                self._send_event(conn, create_event(EventType.DROPS_DISABLED))
                return

            if self._is_self_target(cmd.target):
                self._send_event(conn, create_event(EventType.CANNOT_DROP_SELF))
                return

            resolved = self._cm.resolve_target_for_interaction(cmd.target)

            if resolved:
                alias, onion = resolved
                self._outbox.remember_message_request_id(
                    cmd.msg_id,
                    cmd.request_id,
                )
                self._mm.queue_message(
                    contact_onion=str(onion),
                    direction=MessageDirection.OUT,
                    delivery=Delivery.DROP,
                    content_type=ContentType.TEXT,
                    payload=cmd.content.text,
                    status=MessageStatus.PENDING,
                    msg_id=cmd.msg_id,
                )
                if self._config.get_bool(SettingKey.RECORD_DROP_HISTORY):
                    self._hm.log_event(
                        HistoryEvent.QUEUED,
                        onion,
                        actor=HistoryActor.LOCAL,
                    )

                self._send_event(
                    conn,
                    create_event(
                        EventType.DROP_QUEUED,
                        {'alias': alias, 'onion': onion},
                    ),
                )
            else:
                self._send_event(
                    conn,
                    create_event(
                        EventType.INVALID_TARGET,
                        {'target': cmd.target},
                    ),
                )
