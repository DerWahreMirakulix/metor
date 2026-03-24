"""
Module for managing asynchronous offline messages via SQLite.
Uses strict Enums to represent message states and types.
"""

from enum import Enum
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

from metor.ui.theme import Theme
from metor.utils.constants import Constants
from metor.utils.helper import get_divider_string, get_header_string

# Local Package Imports
from metor.data.profile import ProfileManager
from metor.data.sql import SqlManager
from metor.data.contact import ContactManager


class MessageStatus(str, Enum):
    """
    Represents the exact delivery and read status of an async message.
    """

    PENDING = 'pending'
    DELIVERED = 'delivered'
    UNREAD = 'unread'
    READ = 'read'


class MessageDirection(str, Enum):
    """Represents the flow direction of a message."""

    IN = 'in'
    OUT = 'out'


class MessageType(str, Enum):
    """Represents the payload type of a message."""

    TEXT = 'text'


class MessageManager:
    """Manages the persistence of asynchronous messages (inbox and outbox)."""

    def __init__(self, pm: ProfileManager) -> None:
        """
        Initializes the MessageManager and ensures the database table exists.

        Args:
            pm (ProfileManager): The profile manager instance for context.

        Returns:
            None
        """
        self._pm: ProfileManager = pm
        self._db_path: Path = Path(self._pm.get_config_dir()) / Constants.DB_FILE
        self._sql: SqlManager = SqlManager(self._db_path)
        self._initialize_table()

    def _initialize_table(self) -> None:
        """
        Creates the 'messages' table if it does not already exist.

        Args:
            None

        Returns:
            None
        """
        query: str = """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_onion TEXT NOT NULL,
                direction TEXT NOT NULL,
                msg_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                status TEXT NOT NULL
            )
        """
        self._sql.execute(query)

    def queue_message(
        self,
        contact_onion: str,
        direction: MessageDirection,
        msg_type: MessageType,
        payload: str,
        status: MessageStatus,
    ) -> int:
        """
        Inserts a new message into the database.

        Args:
            contact_onion (str): The onion address of the remote peer.
            direction (MessageDirection): Whether the message is inbound or outbound.
            msg_type (MessageType): The type of payload (e.g., text or voice).
            payload (str): The actual message content or file path.
            status (MessageStatus): The initial status of the message.

        Returns:
            int: The inserted row ID.
        """
        query: str = """
            INSERT INTO messages (contact_onion, direction, msg_type, payload, status) 
            VALUES (?, ?, ?, ?, ?)
        """
        self._sql.execute(
            query,
            (contact_onion, direction.value, msg_type.value, payload, status.value),
        )

        id_query: str = 'SELECT MAX(id) FROM messages'
        result: List[Tuple[int]] = self._sql.fetchall(id_query)
        return int(result[0][0]) if result and result[0][0] else 0

    def get_pending_outbox(self) -> List[Tuple[int, str, str, str]]:
        """
        Retrieves all outbound messages that are waiting to be delivered.

        Args:
            None

        Returns:
            List[Tuple[int, str, str, str]]: A list of database rows representing pending messages.
        """
        query: str = (
            'SELECT id, contact_onion, msg_type, payload FROM messages WHERE status = ?'
        )
        return self._sql.fetchall(query, (MessageStatus.PENDING.value,))

    def update_message_status(self, msg_id: int, new_status: MessageStatus) -> None:
        """
        Updates the delivery or read status of a specific message.

        Args:
            msg_id (int): The unique ID of the message.
            new_status (MessageStatus): The new status to apply.

        Returns:
            None
        """
        query: str = 'UPDATE messages SET status = ? WHERE id = ?'
        self._sql.execute(query, (new_status.value, msg_id))

    def get_unread_counts(self) -> Dict[str, int]:
        """
        Retrieves a count of unread messages grouped by contact onion.

        Args:
            None

        Returns:
            Dict[str, int]: A dictionary mapping onion addresses to their unread message count.
        """
        query: str = 'SELECT contact_onion, COUNT(*) FROM messages WHERE status = ? GROUP BY contact_onion'
        rows: List[Tuple[str, int]] = self._sql.fetchall(
            query, (MessageStatus.UNREAD.value,)
        )

        counts: Dict[str, int] = {}
        for row in rows:
            onion, count = row
            counts[onion] = int(count)

        return counts

    def get_and_read_inbox(self, contact_onion: str) -> List[Tuple[int, str, str, str]]:
        """
        Retrieves all unread messages for a specific contact and marks them as read.

        Args:
            contact_onion (str): The target onion address.

        Returns:
            List[Tuple[int, str, str, str]]: A list of message rows (id, msg_type, payload, timestamp).
        """
        query: str = """
            SELECT id, msg_type, payload, timestamp 
            FROM messages 
            WHERE contact_onion = ? AND status = ?
            ORDER BY timestamp ASC
        """
        messages: List[Tuple[int, str, str, str]] = self._sql.fetchall(
            query, (contact_onion, MessageStatus.UNREAD.value)
        )

        if messages:
            update_query: str = (
                'UPDATE messages SET status = ? WHERE contact_onion = ? AND status = ?'
            )
            self._sql.execute(
                update_query,
                (MessageStatus.READ.value, contact_onion, MessageStatus.UNREAD.value),
            )

        return messages

    def get_chat_history(
        self, contact_onion: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Retrieves the past message history for a specific contact, ordered chronologically.

        Args:
            contact_onion (str): The target onion address.
            limit (int): The maximum number of past messages to fetch. Defaults to 50.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries containing formatted message data.
        """
        query: str = """
            SELECT direction, status, payload, timestamp 
            FROM messages 
            WHERE contact_onion = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """
        rows: List[Tuple[str, str, str, str]] = self._sql.fetchall(
            query, (contact_onion, limit)
        )
        rows.reverse()

        result: List[Dict[str, Any]] = []
        for row in rows:
            direction, status, payload, timestamp = row
            result.append(
                {
                    'direction': direction,
                    'status': status,
                    'payload': payload,
                    'timestamp': timestamp,
                }
            )
        return result

    def clear_messages(self, onion: Optional[str] = None) -> Tuple[bool, str]:
        """
        Wipes the message table completely or just for a specific contact,
        and removes orphaned discovered peers.

        Args:
            onion (Optional[str]): The target onion identity. If None, deletes all.

        Returns:
            Tuple[bool, str]: A success flag and a status message.
        """
        try:
            if onion:
                self._sql.execute(
                    'DELETE FROM messages WHERE contact_onion = ?', (onion,)
                )
                msg = f"All messages for '{onion}' cleared."
            else:
                self._sql.execute('DELETE FROM messages')
                msg = f"All messages in profile '{self._pm.profile_name}' cleared."

            # Cleanup orphaned discovered peers that have no history and no messages left
            cleanup_query: str = """
                DELETE FROM contacts 
                WHERE is_saved = 0 
                AND onion NOT IN (SELECT onion FROM history WHERE onion IS NOT NULL)
                AND onion NOT IN (SELECT contact_onion FROM messages)
            """
            self._sql.execute(cleanup_query)

            return True, msg
        except Exception:
            return False, 'Failed to clear messages.'

    def show_inbox(self, cm: ContactManager) -> str:
        """
        Fetches and formats the current unread inbox counts into a CLI string.

        Args:
            cm (ContactManager): Contact manager instance.

        Returns:
            str: Formatting string output.
        """
        counts: Dict[str, int] = self.get_unread_counts()
        if not counts:
            return 'Inbox is empty.'

        out: str = 'Unread Offline Messages:\n'
        for onion, count in counts.items():
            resolved_alias: str = cm.get_alias_by_onion(onion) or onion
            out += f' - {Theme.CYAN}{resolved_alias}{Theme.RESET}: {Theme.YELLOW}{count}{Theme.RESET} new message(s)\n'

        return out.strip()

    def show_read(self, target: str, cm: ContactManager) -> str:
        """
        Fetches, formats, and marks as read all pending inbox messages for an alias.

        Args:
            target (str): The target string from the CLI (alias or onion).
            cm (ContactManager): Contact manager to resolve the target.

        Returns:
            str: The colorized terminal output displaying the unread messages.
        """
        alias, onion, exists = cm.resolve_target(target)
        if not exists:
            return f"Contact '{target}' not found in address book."

        disp_name: str = alias or str(onion)
        raw_messages: List[Tuple[int, str, str, str]] = self.get_and_read_inbox(
            str(onion)
        )

        if not raw_messages:
            return f"No unread messages from '{disp_name}'."

        out: str = f'{get_header_string(f"Messages from {Theme.CYAN}{disp_name}{Theme.RESET}")}\n'
        for msg in raw_messages:
            timestamp: str = msg[3]
            payload: str = msg[2]

            prefix: str = f'{Theme.PURPLE}From {disp_name}{Theme.RESET}'
            out += f'[{timestamp}] {prefix}: {payload}\n'

        out += get_divider_string()
        return out

    def show_history(self, target: str, cm: ContactManager, limit: int = 50) -> str:
        """
        Fetches and formats the historical message record mimicking the Chat UI colors.

        Args:
            target (str): The target string from the CLI (alias or onion).
            cm (ContactManager): Contact manager to resolve the target.
            limit (int): The number of recent messages to retrieve.

        Returns:
            str: The formatted terminal output of the chat history.
        """
        alias, onion, exists = cm.resolve_target(target)
        if not exists:
            return f"Contact '{target}' not found in address book."

        disp_name: str = alias or str(onion)
        messages: List[Dict[str, Any]] = self.get_chat_history(str(onion), limit)

        if not messages:
            return f"No chat history found for '{disp_name}'."

        out: str = f'{get_header_string(f"Chat History with {Theme.CYAN}{disp_name}{Theme.RESET} (Last {len(messages)})")}\n'
        for msg in messages:
            time_str: str = msg.get('timestamp', '')
            direction: str = msg.get('direction', '')
            status: str = msg.get('status', '')
            payload: str = msg.get('payload', '')

            if direction == MessageDirection.OUT.value:
                if status == MessageStatus.DELIVERED.value:
                    prefix = f'{Theme.GREEN}To {disp_name}{Theme.RESET}'
                else:
                    prefix = f'To {disp_name}'
            else:
                prefix = f'{Theme.PURPLE}From {disp_name}{Theme.RESET}'

            out += f'[{time_str}] {prefix}: {payload}\n'

        out += get_divider_string()
        return out
