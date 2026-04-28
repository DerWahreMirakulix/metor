"""
Module managing the centralized IPC event translation registry.
Ensures the Daemon remains UI-agnostic by resolving strict EventTypes locally.
Preserves the '{alias}' placeholder according to the translation's alias policy.
Utilizes generic status tones instead of chat-specific routing types.
"""

from typing import Dict, Tuple, Optional

from metor.core.api import (
    ConnectionActor,
    ConnectionOrigin,
    ConnectionReasonCode,
    EventType,
    JsonValue,
    RuntimeErrorCode,
)
from metor.utils import TypeCaster

# Local Package Imports
from metor.ui.theme import Theme
from metor.ui.models import AliasPolicy, StatusTone, TranslationDef

ERROR_DETAIL_CODES: set[EventType] = {
    EventType.CONNECTION_FAILED,
    EventType.RETUNNEL_FAILED,
    EventType.TOR_PROCESS_TERMINATED,
    EventType.TOR_START_FAILED,
}

RUNTIME_ERROR_TEXT: dict[RuntimeErrorCode, str] = {
    RuntimeErrorCode.NO_CACHED_DROP_TUNNEL: 'No cached drop tunnel exists',
    RuntimeErrorCode.NO_ACTIVE_CONNECTION_TO_RETUNNEL: (
        'No active connection to retunnel'
    ),
    RuntimeErrorCode.RETUNNEL_RECONNECT_FAILED: 'Retunnel reconnect failed',
    RuntimeErrorCode.PENDING_ACCEPTANCE_EXPIRED: 'Pending acceptance expired',
    RuntimeErrorCode.TOR_LAUNCH_FAILED: 'Failed to launch Tor',
    RuntimeErrorCode.TOR_BINARY_LAUNCH_FAILED: 'Failed to launch the Tor binary',
    RuntimeErrorCode.TOR_PROXY_NOT_READY: 'Tor SOCKS proxy did not become ready',
}

VALIDATION_DETAIL_CODES: set[EventType] = {
    EventType.SETTING_TYPE_ERROR,
}


TRANSLATIONS: Dict[EventType, TranslationDef] = {
    EventType.DAEMON_LOCKED: TranslationDef(
        'Daemon is locked. Please unlock first.', StatusTone.SYSTEM
    ),
    EventType.DAEMON_UNLOCKED: TranslationDef(
        'Daemon unlocked successfully.', StatusTone.SYSTEM
    ),
    EventType.AUTH_REQUIRED: TranslationDef(
        'Authentication required. Please unlock the session first.', StatusTone.SYSTEM
    ),
    EventType.INVALID_PASSWORD: TranslationDef(
        'Invalid master password.', StatusTone.ERROR
    ),
    EventType.LOCAL_AUTH_RATE_LIMITED: TranslationDef(
        'Too many invalid local authentication attempts. Retry in {retry_after}s.',
        StatusTone.ERROR,
    ),
    EventType.DB_CORRUPTED: TranslationDef(
        'Profile database is corrupted.', StatusTone.ERROR
    ),
    EventType.ALREADY_UNLOCKED: TranslationDef(
        'Daemon is already unlocked.', StatusTone.SYSTEM
    ),
    EventType.SESSION_AUTHENTICATED: TranslationDef(
        'Session authenticated successfully.', StatusTone.SYSTEM
    ),
    EventType.SELF_DESTRUCT_INITIATED: TranslationDef(
        'Self-destruct command accepted. Nuking daemon...', StatusTone.SYSTEM
    ),
    EventType.SETTING_UPDATED: TranslationDef(
        f"Global setting '{Theme.YELLOW}{{key}}{Theme.RESET}' updated successfully.",
        StatusTone.SYSTEM,
    ),
    EventType.CONFIG_UPDATED: TranslationDef(
        f"Profile configuration override for '{Theme.YELLOW}{{key}}{Theme.RESET}' updated successfully.",
        StatusTone.SYSTEM,
    ),
    EventType.SETTING_UPDATE_FAILED: TranslationDef(
        'Failed to update global setting.', StatusTone.ERROR
    ),
    EventType.CONFIG_UPDATE_FAILED: TranslationDef(
        'Failed to update profile config.', StatusTone.ERROR
    ),
    EventType.SETTING_TYPE_ERROR: TranslationDef(
        'Invalid value{key}{reason}.', StatusTone.ERROR
    ),
    EventType.INVALID_SETTING_KEY: TranslationDef(
        'Invalid setting key provided.', StatusTone.ERROR
    ),
    EventType.INVALID_CONFIG_KEY: TranslationDef(
        'Invalid profile config key provided.', StatusTone.ERROR
    ),
    EventType.DAEMON_CANNOT_MANAGE_UI: TranslationDef(
        'The Daemon cannot manage UI-specific settings.', StatusTone.ERROR
    ),
    EventType.SETTING_DATA: TranslationDef(
        f"Global Setting '{Theme.YELLOW}{{key}}{Theme.RESET}': {Theme.CYAN}{{value}}{Theme.RESET}",
        StatusTone.SYSTEM,
    ),
    EventType.CONFIG_DATA: TranslationDef(
        f"Profile Config '{Theme.YELLOW}{{key}}{Theme.RESET}': {Theme.CYAN}{{value}}{Theme.RESET}",
        StatusTone.SYSTEM,
    ),
    EventType.CONFIG_SYNCED: TranslationDef(
        'Profile overrides cleared. Config is now synced with global settings.',
        StatusTone.SYSTEM,
    ),
    EventType.UNKNOWN_COMMAND: TranslationDef('Unknown command.', StatusTone.ERROR),
    EventType.INTERNAL_ERROR: TranslationDef(
        'Internal daemon error.', StatusTone.ERROR
    ),
    EventType.TOR_KEY_DECRYPT_FAILED: TranslationDef(
        'Failed to decrypt Tor runtime key.', StatusTone.ERROR
    ),
    EventType.TOR_KEY_WRITE_FAILED: TranslationDef(
        'Failed to provision Tor runtime key on disk.', StatusTone.ERROR
    ),
    EventType.TOR_START_FAILED: TranslationDef(
        'Tor failed to start{error}.', StatusTone.ERROR
    ),
    EventType.TOR_PROCESS_TERMINATED: TranslationDef(
        'Tor process terminated unexpectedly{error}.', StatusTone.ERROR
    ),
    EventType.ADDRESS_CURRENT: TranslationDef(
        "Current onion address for profile '{profile}': {onion}.onion",
        StatusTone.SYSTEM,
    ),
    EventType.ADDRESS_GENERATED: TranslationDef(
        "New onion address generated for profile '{profile}': {onion}.onion",
        StatusTone.SYSTEM,
    ),
    EventType.ADDRESS_CANT_GENERATE_RUNNING: TranslationDef(
        "Changing the address for profile '{profile}' is not possible while a daemon is running.",
        StatusTone.ERROR,
    ),
    EventType.ADDRESS_NOT_GENERATED: TranslationDef(
        "No onion address generated for profile '{profile}' yet. Simply start the daemon or use 'metor address generate'.",
        StatusTone.SYSTEM,
    ),
    EventType.RETUNNEL_FAILED: TranslationDef(
        'Retunnel failed{error}.', StatusTone.ERROR
    ),
    EventType.DAEMON_OFFLINE: TranslationDef(
        'Local daemon is not running.', StatusTone.SYSTEM
    ),
    EventType.IPC_CLIENT_LIMIT_REACHED: TranslationDef(
        'Daemon IPC client limit reached ({max_clients} sessions). Close another local session and retry.',
        StatusTone.ERROR,
    ),
    EventType.CANNOT_CONNECT_SELF: TranslationDef(
        'You cannot connect to yourself.', StatusTone.SYSTEM
    ),
    EventType.INVALID_TARGET: TranslationDef(
        "Target '{target}' not found or invalid.", StatusTone.ERROR
    ),
    EventType.CANNOT_SWITCH_SELF: TranslationDef(
        'You cannot switch focus to yourself.', StatusTone.SYSTEM
    ),
    EventType.NO_CONNECTION_TO_REJECT: TranslationDef(
        "No connection with '{alias}' to reject.",
        StatusTone.SYSTEM,
        AliasPolicy.DYNAMIC,
    ),
    EventType.NO_CONNECTION_TO_DISCONNECT: TranslationDef(
        "No active connection with '{alias}' to disconnect.",
        StatusTone.SYSTEM,
        AliasPolicy.DYNAMIC,
    ),
    EventType.NO_PENDING_CONNECTION: TranslationDef(
        "No pending connection from '{alias}' to accept.",
        StatusTone.INFO,
        AliasPolicy.DYNAMIC,
    ),
    EventType.PENDING_CONNECTION_EXPIRED: TranslationDef(
        "Acceptance window for '{alias}' expired. Try connecting to '{alias}' again.",
        StatusTone.INFO,
        AliasPolicy.DYNAMIC,
    ),
    EventType.MAX_CONNECTIONS_REACHED: TranslationDef(
        "Cannot connect to '{target}'. Maximum concurrent connections ({max_conn}) reached.",
        StatusTone.ERROR,
    ),
    EventType.DROPS_DISABLED: TranslationDef(
        'Async offline messages are disabled by security policy.', StatusTone.SYSTEM
    ),
    EventType.CANNOT_DROP_SELF: TranslationDef(
        'You cannot send offline drops to yourself.', StatusTone.SYSTEM
    ),
    EventType.DROP_QUEUED: TranslationDef(
        "Message successfully queued for '{alias}'.",
        StatusTone.INFO,
        AliasPolicy.DYNAMIC,
    ),
    EventType.AUTO_FALLBACK_QUEUED: TranslationDef(
        "No live connection to '{alias}'. Queued the message as a drop.",
        StatusTone.INFO,
        AliasPolicy.DYNAMIC,
    ),
    EventType.NO_PENDING_LIVE_MSGS: TranslationDef(
        "No pending live messages found for '{alias}'.",
        StatusTone.SYSTEM,
        AliasPolicy.DYNAMIC,
    ),
    EventType.FALLBACK_SUCCESS: TranslationDef(
        "Successfully converted {count} unacked message(s) to '{alias}' into drops.",
        StatusTone.INFO,
        AliasPolicy.DYNAMIC,
    ),
    EventType.CONNECTED: TranslationDef(
        "{origin_text} '{alias}'.",
        StatusTone.INFO,
        AliasPolicy.DYNAMIC,
    ),
    EventType.DISCONNECTED: TranslationDef(
        '{disconnect_text}',
        StatusTone.INFO,
        AliasPolicy.DYNAMIC,
    ),
    EventType.CONNECTION_CONNECTING: TranslationDef(
        "{origin_text} '{alias}'...",
        StatusTone.INFO,
        AliasPolicy.DYNAMIC,
    ),
    EventType.INCOMING_CONNECTION: TranslationDef(
        f"Incoming connection from '{{alias}}'. Type '{Theme.GREEN}/accept {{alias}}{Theme.RESET}' or '{Theme.RED}/reject {{alias}}{Theme.RESET}'.",
        StatusTone.INFO,
        AliasPolicy.DYNAMIC,
    ),
    EventType.CONNECTION_PENDING: TranslationDef(
        "{origin_text} '{alias}'. Waiting for acceptance...",
        StatusTone.INFO,
        AliasPolicy.DYNAMIC,
    ),
    EventType.CONNECTION_AUTO_ACCEPTED: TranslationDef(
        "Pending request found. Auto-accepting connection with '{alias}'...",
        StatusTone.INFO,
        AliasPolicy.DYNAMIC,
    ),
    EventType.CONNECTION_RETRY: TranslationDef(
        "{origin_text} '{alias}' failed. Retrying ({attempt}/{max_retries})...",
        StatusTone.INFO,
        AliasPolicy.DYNAMIC,
    ),
    EventType.CONNECTION_FAILED: TranslationDef(
        "{origin_text} '{alias}' failed{error}.",
        StatusTone.ERROR,
        AliasPolicy.DYNAMIC,
    ),
    EventType.CONNECTION_REJECTED: TranslationDef(
        '{reject_text}',
        StatusTone.INFO,
        AliasPolicy.DYNAMIC,
    ),
    EventType.INBOX_NOTIFICATION: TranslationDef(
        "Received {count} new unread message(s) from '{alias}'.",
        StatusTone.INFO,
        AliasPolicy.DYNAMIC,
    ),
    EventType.AUTO_RECONNECT_SCHEDULED: TranslationDef(
        "Automatic reconnect to '{alias}' scheduled.",
        StatusTone.INFO,
        AliasPolicy.DYNAMIC,
    ),
    EventType.RETUNNEL_INITIATED: TranslationDef(
        "Initiating Tor circuit rotation and retunneling for '{alias}'...",
        StatusTone.INFO,
        AliasPolicy.DYNAMIC,
    ),
    EventType.RETUNNEL_SUCCESS: TranslationDef(
        "Successfully retunneled connection to '{alias}'.",
        StatusTone.INFO,
        AliasPolicy.DYNAMIC,
    ),
    EventType.ALIAS_IN_USE: TranslationDef(
        "Alias '{alias}' is already in use.", StatusTone.SYSTEM
    ),
    EventType.ONION_IN_USE: TranslationDef(
        "The onion is already associated with saved contact '{alias}'.",
        StatusTone.SYSTEM,
        AliasPolicy.DYNAMIC,
    ),
    EventType.CONTACT_ADDED: TranslationDef(
        "Contact '{alias}' added successfully to profile '{profile}'.",
        StatusTone.INFO,
        AliasPolicy.DYNAMIC,
    ),
    EventType.PEER_NOT_FOUND: TranslationDef(
        "Target '{target}' not found.", StatusTone.ERROR
    ),
    EventType.DISCOVERED_PEER_NOT_FOUND: TranslationDef(
        "No discovered peer matching '{target}'.", StatusTone.ERROR
    ),
    EventType.CONTACT_ALREADY_SAVED: TranslationDef(
        "Alias '{alias}' is already saved.",
        StatusTone.SYSTEM,
        AliasPolicy.DYNAMIC,
    ),
    EventType.RENAME_SUCCESS: TranslationDef(
        "Peer alias synchronized from '{old_alias}' to '{new_alias}'.",
        StatusTone.SYSTEM,
    ),
    EventType.PEER_PROMOTED: TranslationDef(
        "Discovered peer '{alias}' saved permanently to address book.",
        StatusTone.INFO,
        AliasPolicy.DYNAMIC,
    ),
    EventType.ALIAS_SAME: TranslationDef(
        'The new alias must be different from the old one.', StatusTone.SYSTEM
    ),
    EventType.ALIAS_NOT_FOUND: TranslationDef(
        "Alias '{alias}' not found.", StatusTone.ERROR
    ),
    EventType.ALIAS_RENAMED: TranslationDef(
        "Alias renamed from '{old_alias}' to '{new_alias}'.", StatusTone.SYSTEM
    ),
    EventType.PEER_CANT_DELETE_ACTIVE: TranslationDef(
        "Discovered peer '{alias}' cannot be deleted manually as it is tied to active states.",
        StatusTone.SYSTEM,
        AliasPolicy.DYNAMIC,
    ),
    EventType.CONTACT_DOWNGRADED: TranslationDef(
        "Contact '{alias}' is now unsaved.",
        StatusTone.INFO,
        AliasPolicy.DYNAMIC,
    ),
    EventType.CONTACT_REMOVED_DOWNGRADED: TranslationDef(
        "Contact '{alias}' removed. Session downgraded to '{new_alias}'.",
        StatusTone.SYSTEM,
    ),
    EventType.PEER_ANONYMIZED: TranslationDef(
        "Discovered peer '{alias}' anonymized to '{new_alias}'.", StatusTone.SYSTEM
    ),
    EventType.CONTACT_REMOVED: TranslationDef(
        "Contact '{alias}' removed from profile '{profile}'.",
        StatusTone.INFO,
        AliasPolicy.DYNAMIC,
    ),
    EventType.PEER_REMOVED: TranslationDef(
        "Discovered peer '{alias}' removed.",
        StatusTone.INFO,
        AliasPolicy.DYNAMIC,
    ),
    EventType.CONTACTS_CLEARED: TranslationDef(
        "Address book for profile '{profile}' cleared{preserved_peers_suffix}.",
        StatusTone.SYSTEM,
    ),
    EventType.CONTACTS_CLEAR_FAILED: TranslationDef(
        'Failed to clear contacts.', StatusTone.ERROR
    ),
    EventType.HISTORY_CLEARED: TranslationDef(
        "History for '{alias}' cleared.",
        StatusTone.INFO,
        AliasPolicy.DYNAMIC,
    ),
    EventType.HISTORY_CLEARED_ALL: TranslationDef(
        "History for profile '{profile}' cleared.", StatusTone.SYSTEM
    ),
    EventType.HISTORY_CLEAR_FAILED: TranslationDef(
        'Failed to clear history.', StatusTone.ERROR
    ),
    EventType.MESSAGES_CLEARED: TranslationDef(
        "All messages for '{alias}' cleared.",
        StatusTone.INFO,
        AliasPolicy.DYNAMIC,
    ),
    EventType.MESSAGES_CLEARED_NON_CONTACTS: TranslationDef(
        "Messages for non-contact '{alias}' cleared.",
        StatusTone.INFO,
        AliasPolicy.DYNAMIC,
    ),
    EventType.MESSAGES_CLEARED_NON_CONTACTS_ALL: TranslationDef(
        "Messages for non-contacts in profile '{profile}' cleared.",
        StatusTone.SYSTEM,
    ),
    EventType.MESSAGES_CLEARED_ALL: TranslationDef(
        "All messages in profile '{profile}' cleared.", StatusTone.SYSTEM
    ),
    EventType.MESSAGES_CLEAR_FAILED: TranslationDef(
        'Failed to clear messages.', StatusTone.ERROR
    ),
    EventType.DB_CLEARED: TranslationDef(
        "Database for profile '{profile}' cleared{preserved_peers_suffix}.",
        StatusTone.SYSTEM,
    ),
    EventType.DB_CLEAR_FAILED: TranslationDef(
        'Error clearing database.', StatusTone.ERROR
    ),
}


class Translator:
    """Provides dynamic text translations based on strict daemon EventTypes."""

    @staticmethod
    def _build_preserved_peers_suffix(
        code: EventType,
        preserved_peers_raw: Optional[JsonValue],
    ) -> str:
        """
        Builds one partial-clear suffix when anonymized discovered peers remain.

        Args:
            code (EventType): The clear-result event code.
            preserved_peers_raw (Optional[JsonValue]): The raw preserved-peer count.

        Returns:
            str: One localized suffix including the leading separator when needed.
        """
        preserved_peers: int = 0
        if isinstance(preserved_peers_raw, int):
            preserved_peers = max(0, preserved_peers_raw)
        elif (
            isinstance(preserved_peers_raw, float) and preserved_peers_raw.is_integer()
        ):
            preserved_peers = max(0, int(preserved_peers_raw))
        elif isinstance(preserved_peers_raw, str) and preserved_peers_raw.isdigit():
            preserved_peers = max(0, int(preserved_peers_raw))

        if preserved_peers <= 0:
            return ''

        peer_label: str = 'active peer' if code is EventType.DB_CLEARED else 'peer'
        if preserved_peers != 1:
            peer_label += 's'
        verb: str = 'was' if preserved_peers == 1 else 'were'
        discovered_label: str = (
            'anonymized discovered peer'
            if preserved_peers == 1
            else 'anonymized discovered peers'
        )
        article: str = 'an ' if preserved_peers == 1 else ''

        return (
            f', but {preserved_peers} {peer_label} {verb} preserved as '
            f'{article}{discovered_label}'
        )

    @staticmethod
    def _resolve_connection_origin(
        origin: Optional[JsonValue],
    ) -> ConnectionOrigin:
        """
        Coerces one raw origin payload to a strict connection origin.

        Args:
            origin (Optional[JsonValue]): The raw IPC parameter.

        Returns:
            ConnectionOrigin: The normalized connection origin.
        """
        return TypeCaster.to_enum(
            ConnectionOrigin,
            origin,
            ConnectionOrigin.MANUAL,
        )

    @staticmethod
    def _resolve_connection_actor(
        actor: Optional[JsonValue],
    ) -> ConnectionActor:
        """
        Coerces one raw actor payload to a strict connection actor.

        Args:
            actor (Optional[JsonValue]): The raw IPC parameter.

        Returns:
            ConnectionActor: The normalized connection actor.
        """
        return TypeCaster.to_enum(
            ConnectionActor,
            actor,
            ConnectionActor.SYSTEM,
        )

    @staticmethod
    def _resolve_connection_reason_code(
        reason_code: Optional[JsonValue],
    ) -> Optional[ConnectionReasonCode]:
        """
        Coerces one raw reason-code payload to a strict lifecycle reason.

        Args:
            reason_code (Optional[JsonValue]): The raw IPC parameter.

        Returns:
            Optional[ConnectionReasonCode]: The normalized reason code if valid.
        """
        return TypeCaster.to_optional_enum(ConnectionReasonCode, reason_code)

    @staticmethod
    def _apply_connection_origin_params(
        code: EventType,
        safe_params: Dict[str, JsonValue],
    ) -> None:
        """
        Derives one human-readable origin phrase for connection lifecycle events.

        Args:
            code (EventType): The strict daemon event identifier.
            safe_params (Dict[str, JsonValue]): Mutable translation parameters.

        Returns:
            None
        """
        origin: ConnectionOrigin = Translator._resolve_connection_origin(
            safe_params.get('origin')
        )
        actor: ConnectionActor = Translator._resolve_connection_actor(
            safe_params.get('actor')
        )
        reason_code: Optional[ConnectionReasonCode] = (
            Translator._resolve_connection_reason_code(safe_params.get('reason_code'))
        )

        if code is EventType.CONNECTED:
            if origin in (
                ConnectionOrigin.AUTO_RECONNECT,
                ConnectionOrigin.GRACE_RECONNECT,
            ):
                safe_params['origin_text'] = 'Reconnected to'
            else:
                safe_params['origin_text'] = 'Connected to'
            return

        if code is EventType.CONNECTION_CONNECTING:
            if origin is ConnectionOrigin.AUTO_RECONNECT:
                safe_params['origin_text'] = 'Automatically reconnecting to'
            elif origin is ConnectionOrigin.GRACE_RECONNECT:
                safe_params['origin_text'] = 'Reconnecting to'
            elif origin is ConnectionOrigin.RETUNNEL:
                safe_params['origin_text'] = 'Retunnel reconnecting to'
            else:
                safe_params['origin_text'] = 'Connecting to'
            return

        if code is EventType.CONNECTION_PENDING:
            if origin is ConnectionOrigin.AUTO_RECONNECT:
                safe_params['origin_text'] = 'Automatic reconnect request sent to'
            elif origin is ConnectionOrigin.GRACE_RECONNECT:
                safe_params['origin_text'] = 'Reconnect request sent to'
            elif origin is ConnectionOrigin.RETUNNEL:
                safe_params['origin_text'] = 'Retunnel reconnect request sent to'
            else:
                safe_params['origin_text'] = 'Request sent to'
            return

        if code in (EventType.CONNECTION_RETRY, EventType.CONNECTION_FAILED):
            if origin is ConnectionOrigin.AUTO_RECONNECT:
                safe_params['origin_text'] = 'Automatic reconnect to'
            elif origin is ConnectionOrigin.GRACE_RECONNECT:
                safe_params['origin_text'] = 'Reconnect to'
            elif origin is ConnectionOrigin.RETUNNEL:
                safe_params['origin_text'] = 'Retunnel reconnect to'
            else:
                safe_params['origin_text'] = 'Connection to'
            return

        if code is EventType.CONNECTION_REJECTED:
            if actor is ConnectionActor.LOCAL:
                safe_params['reject_text'] = "Rejected connection with '{alias}'."
                return
            if origin is ConnectionOrigin.AUTO_RECONNECT:
                safe_params['reject_text'] = (
                    "Automatic reconnect to '{alias}' rejected."
                )
            elif origin is ConnectionOrigin.GRACE_RECONNECT:
                safe_params['reject_text'] = "Reconnect to '{alias}' rejected."
            elif origin is ConnectionOrigin.RETUNNEL:
                safe_params['reject_text'] = "Retunnel reconnect to '{alias}' rejected."
            else:
                safe_params['reject_text'] = "Connection with '{alias}' rejected."
            return

        if code is EventType.DISCONNECTED:
            if actor is ConnectionActor.REMOTE:
                safe_params['disconnect_text'] = "Peer '{alias}' disconnected."
            elif actor is ConnectionActor.SYSTEM or reason_code is not None:
                safe_params['disconnect_text'] = "Connection to '{alias}' lost."
            else:
                safe_params['disconnect_text'] = "Disconnected from '{alias}'."

    @staticmethod
    def get_alias_policy(code: EventType) -> AliasPolicy:
        """
        Returns the alias binding policy for one translated event.

        Args:
            code (EventType): The rigid daemon event identifier.

        Returns:
            AliasPolicy: The alias binding policy for the event.
        """
        entry: Optional[TranslationDef] = TRANSLATIONS.get(code)
        if not entry:
            return AliasPolicy.NONE
        return entry.alias_policy

    @staticmethod
    def get(
        code: EventType, params: Optional[Dict[str, JsonValue]] = None
    ) -> Tuple[str, StatusTone]:
        """
        Resolves a translation code to its localized string and status tone.
        Preserves the '{alias}' placeholder according to the translation alias policy.

        Args:
            code (EventType): The rigid daemon event identifier.
            params (Optional[Dict[str, JsonValue]]): Dynamic parameters to inject (e.g., attempt counts).

        Returns:
            Tuple[str, StatusTone]: The formatted text and its status tone.
        """
        entry: Optional[TranslationDef] = TRANSLATIONS.get(code)
        if not entry:
            return f'Unknown code: {code}', StatusTone.SYSTEM

        safe_params: Dict[str, JsonValue] = params.copy() if params else {}

        if code in ERROR_DETAIL_CODES:
            error_text: str = ''
            raw_error_code = safe_params.get('error_code')
            if raw_error_code is not None:
                try:
                    error_code: RuntimeErrorCode = RuntimeErrorCode(str(raw_error_code))
                    error_text = RUNTIME_ERROR_TEXT.get(error_code, '')
                except ValueError:
                    error_text = ''

            if not error_text:
                error_text = str(safe_params.get('error') or '').strip()

            error_detail_text: str = str(safe_params.get('error_detail') or '').strip()
            if error_detail_text:
                if error_text:
                    error_text = f'{error_text}: {error_detail_text}'
                else:
                    error_text = error_detail_text

            error_text = error_text.rstrip('.')
            safe_params['error'] = f': {error_text}' if error_text else ''

        if code in VALIDATION_DETAIL_CODES:
            key_text: str = str(safe_params.get('key') or '').strip()
            reason_text: str = str(safe_params.get('reason') or '').strip()
            reason_text = reason_text.rstrip('.')
            safe_params['key'] = (
                f" for '{Theme.YELLOW}{key_text}{Theme.RESET}'" if key_text else ''
            )
            safe_params['reason'] = f': {reason_text}' if reason_text else ''

        if code in {EventType.CONTACTS_CLEARED, EventType.DB_CLEARED}:
            safe_params['preserved_peers_suffix'] = (
                Translator._build_preserved_peers_suffix(
                    code,
                    safe_params.get('preserved_peers'),
                )
            )

        if code in {
            EventType.CONNECTED,
            EventType.DISCONNECTED,
            EventType.CONNECTION_CONNECTING,
            EventType.CONNECTION_PENDING,
            EventType.CONNECTION_RETRY,
            EventType.CONNECTION_FAILED,
            EventType.CONNECTION_REJECTED,
        }:
            Translator._apply_connection_origin_params(code, safe_params)

        # Preserve '{alias}' only for messages that explicitly opt into
        # dynamic peer-bound alias redraws.
        if entry.alias_policy is AliasPolicy.DYNAMIC:
            if 'alias' in safe_params and safe_params['alias']:
                safe_params['alias'] = '{alias}'
            else:
                safe_params.setdefault('alias', '{alias}')
        elif '{alias}' in entry.text and not safe_params.get('alias'):
            safe_params['alias'] = 'unknown'

        try:
            text: str = entry.text.format(**safe_params)
            return text, entry.tone
        except Exception as e:
            return f'Translation error ({code}): {str(e)}', StatusTone.ERROR
