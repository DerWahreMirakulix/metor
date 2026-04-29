"""Message persistence service backed by the centralized SQL message store."""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from metor.data.message.models import (
    MessageClearOperationType,
    MessageClearResult,
    MessageDirection,
    MessageStatus,
    MessageType,
    QueuedMessageResult,
    StoredMessageRecord,
)
from metor.data.profile import ProfileManager
from metor.data.settings import SettingKey
from metor.data.sql import MessageRepository, SqlManager


class MessageManager:
    """Manages the persistence of asynchronous messages (inbox and outbox)."""

    def __init__(self, pm: ProfileManager, password: Optional[str] = None) -> None:
        """
        Initializes the message manager and its centralized persistence repository.

        Args:
            pm (ProfileManager): The profile manager instance for context.
            password (Optional[str]): The master password for SQLCipher encryption.

        Returns:
            None
        """
        self._pm: ProfileManager = pm
        self._db_path: Path = self._pm.paths.get_db_file()
        self._sql: SqlManager = SqlManager(self._db_path, self._pm.config, password)
        self._messages: MessageRepository = self._sql.messages

    def queue_message(
        self,
        contact_onion: str,
        direction: MessageDirection,
        msg_type: MessageType,
        payload: str,
        status: MessageStatus,
        msg_id: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> QueuedMessageResult:
        """
        Inserts one logical message into durable storage.

        Args:
            contact_onion (str): The onion address of the remote peer.
            direction (MessageDirection): Whether the message is inbound or outbound.
            msg_type (MessageType): The type of payload.
            payload (str): The actual message content.
            status (MessageStatus): The initial persisted status.
            msg_id (Optional[str]): Stable logical message id.
            timestamp (Optional[str]): Stable authored ISO timestamp.

        Returns:
            QueuedMessageResult: The inserted receipt id and duplicate flag.
        """
        return self._messages.queue_message(
            contact_onion=contact_onion,
            direction=direction,
            msg_type=msg_type,
            payload=payload,
            status=status,
            msg_id=msg_id,
            timestamp=timestamp,
        )

    def has_inbound_message(self, contact_onion: str, msg_id: str) -> bool:
        """
        Checks whether one inbound logical message already exists durably.

        Args:
            contact_onion (str): The remote onion identity.
            msg_id (str): The stable logical message identifier.

        Returns:
            bool: True if a matching inbound row already exists.
        """
        return self._messages.has_inbound_message(contact_onion, msg_id)

    def get_unread_live_count(self, contact_onion: str) -> int:
        """
        Counts crash-safe inbound live messages awaiting explicit consume.

        Args:
            contact_onion (str): The remote onion identity.

        Returns:
            int: The unread inbound live-message backlog for the peer.
        """
        return self._messages.count_unread_by_type(contact_onion, MessageType.LIVE_TEXT)

    def get_unread_drop_count(self, contact_onion: str) -> int:
        """
        Counts unread inbound drop messages currently retained for one peer.

        Args:
            contact_onion (str): The remote onion identity.

        Returns:
            int: The unread inbound drop-message backlog for the peer.
        """
        return self._messages.count_unread_by_type(contact_onion, MessageType.DROP_TEXT)

    def get_pending_outbox(self) -> List[Tuple[int, str, str, str, str, str]]:
        """
        Retrieves all outbound drop-visible messages waiting to be delivered.

        Args:
            None

        Returns:
            List[Tuple[int, str, str, str, str, str]]: Pending outbox rows.
        """
        return self._messages.get_pending_outbox()

    def get_pending_live_outbox(
        self,
        contact_onion: Optional[str] = None,
    ) -> List[Tuple[int, str, str, str, str]]:
        """
        Retrieves all durable outbound live messages waiting for recovery or ACK.

        Args:
            contact_onion (Optional[str]): Optional peer onion filter.

        Returns:
            List[Tuple[int, str, str, str, str]]: Pending live rows.
        """
        return self._messages.get_pending_live_outbox(contact_onion)

    def update_message_status(self, msg_id: int, new_status: MessageStatus) -> None:
        """
        Updates the delivery or read status of a specific durable message receipt.

        Args:
            msg_id (int): The durable internal receipt id.
            new_status (MessageStatus): The new status to apply.

        Returns:
            None
        """
        self._messages.update_message_status(msg_id, new_status)

    def update_outbound_message_status(
        self,
        contact_onion: str,
        msg_id: str,
        new_status: MessageStatus,
    ) -> bool:
        """
        Updates the status of one outbound logical message using its stable ID.

        Args:
            contact_onion (str): The peer onion identity.
            msg_id (str): The logical message identifier.
            new_status (MessageStatus): The new status to apply.

        Returns:
            bool: True if a matching outbound receipt was updated.
        """
        return self._messages.update_outbound_message_status(
            contact_onion,
            msg_id,
            new_status,
        )

    def get_unread_counts(self) -> Dict[str, int]:
        """
        Retrieves unread counts grouped by peer onion.

        Args:
            None

        Returns:
            Dict[str, int]: A dictionary mapping onion addresses to unread counts.
        """
        return self._messages.get_unread_counts()

    def get_and_read_inbox(self, contact_onion: str) -> List[Tuple[int, str, str, str]]:
        """
        Retrieves unread inbox rows for one contact and executes the consume policy.

        Args:
            contact_onion (str): The target onion address.

        Returns:
            List[Tuple[int, str, str, str]]: Message rows as receipt id, type, payload, timestamp.
        """
        return self._messages.get_and_read_inbox(
            contact_onion,
            self._pm.config.get_bool(SettingKey.EPHEMERAL_MESSAGES),
        )

    def get_chat_history(
        self,
        contact_onion: str,
        limit: Optional[int] = None,
    ) -> List[StoredMessageRecord]:
        """
        Retrieves the visible chat history for a specific contact.

        Args:
            contact_onion (str): The target onion address.
            limit (Optional[int]): The maximum number of past messages to fetch.

        Returns:
            List[StoredMessageRecord]: Typed persisted message rows.
        """
        actual_limit: int = (
            limit
            if limit is not None
            else self._pm.config.get_int(SettingKey.MESSAGES_LIMIT)
        )
        return self._messages.get_chat_history(contact_onion, actual_limit)

    def clear_messages(
        self,
        onion: Optional[str] = None,
        non_contacts_only: bool = False,
    ) -> MessageClearResult:
        """
        Clears persisted message state globally or for one peer.

        Args:
            onion (Optional[str]): The target onion identity.
            non_contacts_only (bool): If True, only deletes messages from unsaved peers.

        Returns:
            MessageClearResult: The typed clear-messages result.
        """
        try:
            self._messages.clear_messages(onion, non_contacts_only)
            if non_contacts_only:
                if onion:
                    return MessageClearResult(
                        True,
                        MessageClearOperationType.NON_CONTACTS_TARGET_CLEARED,
                        target_onion=onion,
                    )
                return MessageClearResult(
                    True,
                    MessageClearOperationType.NON_CONTACTS_ALL_CLEARED,
                    profile=self._pm.profile_name,
                )

            if onion:
                return MessageClearResult(
                    True,
                    MessageClearOperationType.TARGET_CLEARED,
                    target_onion=onion,
                )

            return MessageClearResult(
                True,
                MessageClearOperationType.ALL_CLEARED,
                profile=self._pm.profile_name,
            )
        except Exception:
            return MessageClearResult(
                False,
                MessageClearOperationType.CLEAR_FAILED,
            )
