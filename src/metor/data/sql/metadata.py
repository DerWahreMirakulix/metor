"""Profile-owned metadata with stable identity and revision-qualified atomic writes."""

import json
from typing import TYPE_CHECKING

from metor.shared import Constants

# Local Package Imports
from .backends import SqlCipherCursor

if TYPE_CHECKING:
    from .manager import SqlManager


class ProfileMetadataRepository:
    """Owns the bounded protected GUI namespace without storing contact aliases."""

    def __init__(self, sql: 'SqlManager', protected: bool) -> None:
        """Binds metadata to the selected profile's existing SQLCipher connection.

        Args:
            sql: Owning profile database manager.
            protected: Whether the profile's database uses a protection key.
        Returns:
            None
        """
        self._sql = sql
        self._protected = protected

    @property
    def instance_id(self) -> str:
        """Reads the stable profile identity without deriving it from name/address.

        Args:
            None
        Returns:
            str: Persisted opaque profile identity.
        """
        rows = self._sql.fetchall(
            'SELECT value FROM profile_metadata WHERE name = ?', ('instance_id',)
        )
        if not rows or not isinstance(rows[0][0], str):
            raise ValueError('Profile instance metadata is unavailable')
        value = rows[0][0]
        if len(value) != Constants.PROFILE_INSTANCE_BYTES * 2:
            raise ValueError('Profile instance metadata is invalid')
        try:
            bytes.fromhex(value)
        except ValueError as exc:
            raise ValueError('Profile instance metadata is invalid') from exc
        return value

    def read_gui(self) -> tuple[int, str | None]:
        """Reads one bounded GUI document without granting a plaintext fallback.

        Args:
            None
        Returns:
            tuple[int, str | None]: Current revision and optional protected document.
        """
        if not self._protected:
            raise PermissionError('Protected profile metadata is unavailable')
        rows = self._sql.fetchall(
            'SELECT revision, value FROM profile_metadata WHERE name = ?', ('ui.gui',)
        )
        if not rows:
            return 0, None
        revision, value = rows[0]
        if type(revision) is not int or not isinstance(value, str):
            raise ValueError('Invalid profile metadata')
        if len(value.encode('utf-8')) > Constants.GUI_METADATA_MAX_BYTES:
            raise ValueError('Profile metadata exceeds its bound')
        return revision, value

    def write_gui(self, expected_revision: int, value: str) -> int | None:
        """Atomically replaces the protected namespace when its revision matches.

        Args:
            expected_revision: Revision read by the authorized caller.
            value: Validated bounded GUI document from the owning policy service.
        Returns:
            int | None: Accepted revision or a concurrent-update conflict.
        """
        if not self._protected:
            raise PermissionError('Protected profile metadata is unavailable')
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError('Invalid profile metadata revision')
        if len(value.encode('utf-8')) > Constants.GUI_METADATA_MAX_BYTES:
            raise ValueError('Profile metadata exceeds its bound')
        with self._sql.transaction() as cursor:
            cursor.execute(
                'SELECT revision FROM profile_metadata WHERE name = ?', ('ui.gui',)
            )
            row = cursor.fetchone()
            if row is not None and (
                not isinstance(row, tuple) or len(row) != 1 or type(row[0]) is not int
            ):
                raise ValueError('Invalid profile metadata revision')
            revision: int = row[0] if isinstance(row, tuple) else 0
            if revision != expected_revision:
                return None
            next_revision = revision + 1
            cursor.execute(
                'INSERT INTO profile_metadata (name, revision, value) VALUES (?, ?, ?) '
                'ON CONFLICT(name) DO UPDATE SET revision = excluded.revision, value = excluded.value '
                'WHERE profile_metadata.revision = ?',
                ('ui.gui', next_revision, value, expected_revision),
            )
            cursor.execute('SELECT changes()')
            changed = cursor.fetchone()
            return (
                next_revision
                if isinstance(changed, tuple) and changed == (1,)
                else None
            )

    @staticmethod
    def prune_pins(cursor: SqlCipherCursor, removed: set[str]) -> None:
        """Removes deleted peer/conversation pins in the owning SQL transaction.

        Args:
            cursor: Existing peer or DROP-clear transaction.
            removed: Canonical identities whose pin lifetime has ended.
        Returns:
            None
        """
        if not removed:
            return
        cursor.execute('SELECT value FROM profile_metadata WHERE name = ?', ('ui.gui',))
        row = cursor.fetchone()
        if row is None:
            return
        if not isinstance(row, tuple) or not isinstance(row[0], str):
            raise ValueError('Invalid profile metadata')
        if len(row[0].encode('utf-8')) > Constants.GUI_METADATA_MAX_BYTES:
            raise ValueError('Profile metadata exceeds its bound')
        document = json.loads(row[0])
        if not isinstance(document, dict):
            raise ValueError('Invalid profile metadata')
        pins = document.get('pins', [])
        if not isinstance(pins, list) or not all(
            isinstance(peer, str) for peer in pins
        ):
            raise ValueError('Invalid profile pins')
        remaining = [peer for peer in pins if peer not in removed]
        if remaining != pins:
            document['pins'] = remaining
            cursor.execute(
                'UPDATE profile_metadata SET value = ?, revision = revision + 1 WHERE name = ?',
                (json.dumps(document, separators=(',', ':')), 'ui.gui'),
            )
