"""
Module managing the centralized IPC event translation registry.
Ensures the Daemon remains UI-agnostic by resolving strict EventTypes locally.
Preserves the '{alias}' placeholder only for info-tone status lines.
Utilizes generic status tones instead of chat-specific routing types.
"""

from typing import Dict, Tuple, Optional

from metor.core.api import EventType, JsonValue

# Local Package Imports
from metor.ui.theme import Theme
from metor.ui.models import StatusTone, TranslationDef


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
        'Type parsing error.', StatusTone.ERROR
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
    EventType.TOR_KEY_ERROR: TranslationDef('Tor key error.', StatusTone.ERROR),
    EventType.TOR_START_FAILED: TranslationDef(
        'Tor failed to start.', StatusTone.ERROR
    ),
    EventType.TOR_PROCESS_TERMINATED: TranslationDef(
        'Tor process terminated unexpectedly.', StatusTone.ERROR
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
        "No connection with '{alias}' to reject.", StatusTone.SYSTEM
    ),
    EventType.NO_CONNECTION_TO_DISCONNECT: TranslationDef(
        "No active connection with '{alias}' to disconnect.", StatusTone.SYSTEM
    ),
    EventType.NO_PENDING_CONNECTION: TranslationDef(
        "No pending connection from '{alias}' to accept.", StatusTone.INFO
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
        "Message successfully queued for '{alias}'.", StatusTone.INFO
    ),
    EventType.NO_PENDING_LIVE_MSGS: TranslationDef(
        "No pending live messages found for '{alias}'.", StatusTone.SYSTEM
    ),
    EventType.FALLBACK_SUCCESS: TranslationDef(
        "Successfully converted {count} unacked message(s) to '{alias}' into drops.",
        StatusTone.INFO,
    ),
    EventType.CONNECTED: TranslationDef("Connected to '{alias}'.", StatusTone.INFO),
    EventType.DISCONNECTED: TranslationDef(
        "Disconnected from '{alias}'.", StatusTone.INFO
    ),
    EventType.CONNECTION_CONNECTING: TranslationDef(
        "Connecting to '{alias}'...", StatusTone.INFO
    ),
    EventType.INCOMING_CONNECTION: TranslationDef(
        f"Incoming connection from '{{alias}}'. Type '{Theme.GREEN}/accept {{alias}}{Theme.RESET}' or '{Theme.RED}/reject {{alias}}{Theme.RESET}'.",
        StatusTone.INFO,
    ),
    EventType.CONNECTION_PENDING: TranslationDef(
        "Request sent to '{alias}'. Waiting for acceptance...", StatusTone.INFO
    ),
    EventType.CONNECTION_AUTO_ACCEPTED: TranslationDef(
        "Pending request found. Auto-accepting connection with '{alias}'...",
        StatusTone.INFO,
    ),
    EventType.CONNECTION_RETRY: TranslationDef(
        "Connecting to '{alias}' failed. Retrying ({attempt}/{max_retries})...",
        StatusTone.INFO,
    ),
    EventType.CONNECTION_FAILED: TranslationDef(
        "Failed to connect to '{alias}'.", StatusTone.ERROR
    ),
    EventType.CONNECTION_REJECTED: TranslationDef(
        "Connection with '{alias}' rejected.", StatusTone.INFO
    ),
    EventType.INBOX_NOTIFICATION: TranslationDef(
        "Received {count} new offline message(s) from '{alias}'.", StatusTone.INFO
    ),
    EventType.AUTO_RECONNECT_ATTEMPT: TranslationDef(
        "Attempting automatic reconnect to '{alias}'...", StatusTone.INFO
    ),
    EventType.RETUNNEL_INITIATED: TranslationDef(
        "Initiating Tor circuit rotation and retunneling for '{alias}'...",
        StatusTone.INFO,
    ),
    EventType.RETUNNEL_SUCCESS: TranslationDef(
        "Successfully retunneled connection to '{alias}'.", StatusTone.INFO
    ),
    EventType.ALIAS_IN_USE: TranslationDef(
        "Alias '{alias}' is already in use.", StatusTone.SYSTEM
    ),
    EventType.ONION_IN_USE: TranslationDef(
        "The onion is already associated with saved contact '{alias}'.",
        StatusTone.SYSTEM,
    ),
    EventType.CONTACT_ADDED: TranslationDef(
        "Contact '{alias}' added successfully to profile '{profile}'.", StatusTone.INFO
    ),
    EventType.PEER_NOT_FOUND: TranslationDef(
        "Target '{target}' not found.", StatusTone.ERROR
    ),
    EventType.CONTACT_ALREADY_SAVED: TranslationDef(
        "Alias '{alias}' is already saved.", StatusTone.SYSTEM
    ),
    EventType.PEER_PROMOTED: TranslationDef(
        "Discovered peer '{alias}' saved permanently to address book.", StatusTone.INFO
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
    ),
    EventType.CONTACT_DOWNGRADED: TranslationDef(
        "Contact '{alias}' is now unsaved.", StatusTone.INFO
    ),
    EventType.CONTACT_REMOVED_DOWNGRADED: TranslationDef(
        "Contact '{alias}' removed. Session downgraded to '{new_alias}'.",
        StatusTone.SYSTEM,
    ),
    EventType.PEER_ANONYMIZED: TranslationDef(
        "Discovered peer '{alias}' anonymized to '{new_alias}'.", StatusTone.SYSTEM
    ),
    EventType.CONTACT_REMOVED: TranslationDef(
        "Contact '{alias}' removed from profile '{profile}'.", StatusTone.INFO
    ),
    EventType.PEER_REMOVED: TranslationDef(
        "Discovered peer '{alias}' removed.", StatusTone.INFO
    ),
    EventType.CONTACTS_CLEARED: TranslationDef(
        "All contacts cleared and active peers anonymized for profile '{profile}'.",
        StatusTone.SYSTEM,
    ),
    EventType.CONTACTS_CLEAR_FAILED: TranslationDef(
        'Failed to clear contacts.', StatusTone.ERROR
    ),
    EventType.HISTORY_CLEARED: TranslationDef(
        "History for '{alias}' cleared.", StatusTone.INFO
    ),
    EventType.HISTORY_CLEARED_ALL: TranslationDef(
        "History for profile '{profile}' cleared.", StatusTone.SYSTEM
    ),
    EventType.HISTORY_CLEAR_FAILED: TranslationDef(
        'Failed to clear history.', StatusTone.ERROR
    ),
    EventType.MESSAGES_CLEARED: TranslationDef(
        "All messages for '{alias}' cleared.", StatusTone.INFO
    ),
    EventType.MESSAGES_CLEARED_NON_CONTACTS: TranslationDef(
        "Messages for non-contact '{alias}' cleared.", StatusTone.INFO
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
        "Database for profile '{profile}' successfully cleared.", StatusTone.SYSTEM
    ),
    EventType.DB_CLEAR_FAILED: TranslationDef(
        'Error clearing database.', StatusTone.ERROR
    ),
}


class Translator:
    """Provides dynamic text translations based on strict daemon EventTypes."""

    @staticmethod
    def get(
        code: EventType, params: Optional[Dict[str, JsonValue]] = None
    ) -> Tuple[str, StatusTone]:
        """
        Resolves a translation code to its localized string and status tone.
        Preserves the '{alias}' placeholder only for info-tone chat rendering.

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

        if code is EventType.RETUNNEL_FAILED:
            error_text: str = str(safe_params.get('error') or '').strip()
            safe_params['error'] = f': {error_text}' if error_text else ''

        # Preserve '{alias}' only for info-tone chat rendering so later alias
        # renames can still rehydrate informational status lines dynamically.
        if entry.tone is StatusTone.INFO:
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
