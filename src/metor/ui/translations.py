"""
Module managing the centralized UI translation and formatting registry.
Ensures the Daemon remains UI-agnostic by providing text resolutions locally.
Preserves the '{alias}' placeholder strictly for downstream dynamic rendering.
Utilizes domain-agnostic UISeverity Enums instead of Chat-specific routing types.
"""

from typing import Dict, Tuple, Optional

from metor.core.api import (
    DomainCode,
    SystemCode,
    NetworkCode,
    DbCode,
    ContactCode,
    UiCode,
    JsonValue,
)

# Local Package Imports
from metor.ui.theme import Theme
from metor.ui.models import UISeverity, TranslationDef


TRANSLATIONS: Dict[DomainCode, TranslationDef] = {
    # System / General
    SystemCode.DAEMON_LOCKED: TranslationDef(
        'Daemon is locked. Please unlock first.', UISeverity.SYSTEM
    ),
    SystemCode.DAEMON_UNLOCKED: TranslationDef(
        'Daemon unlocked successfully.', UISeverity.SYSTEM
    ),
    SystemCode.AUTH_REQUIRED: TranslationDef(
        'Authentication required. Please unlock the session first.', UISeverity.SYSTEM
    ),
    SystemCode.INVALID_PASSWORD: TranslationDef(
        'Invalid master password.', UISeverity.ERROR
    ),
    SystemCode.ALREADY_UNLOCKED: TranslationDef(
        'Daemon is already unlocked.', UISeverity.SYSTEM
    ),
    SystemCode.SESSION_AUTHENTICATED: TranslationDef(
        'Session authenticated successfully.', UISeverity.SYSTEM
    ),
    SystemCode.SELF_DESTRUCT_INITIATED: TranslationDef(
        'Self-destruct command accepted. Nuking daemon...', UISeverity.SYSTEM
    ),
    SystemCode.SETTING_UPDATED: TranslationDef(
        "Global setting '{key}' updated successfully.", UISeverity.SYSTEM
    ),
    SystemCode.CONFIG_UPDATED: TranslationDef(
        "Profile configuration override for '{key}' updated successfully.",
        UISeverity.SYSTEM,
    ),
    SystemCode.SETTING_UPDATE_FAILED: TranslationDef(
        'Failed to update global setting: {error}', UISeverity.ERROR
    ),
    SystemCode.CONFIG_UPDATE_FAILED: TranslationDef(
        'Failed to update profile config: {error}', UISeverity.ERROR
    ),
    SystemCode.SETTING_TYPE_ERROR: TranslationDef(
        'Type parsing error: {error}', UISeverity.ERROR
    ),
    SystemCode.SETTING_DATA: TranslationDef(
        "Global Setting '{key}': {value}", UISeverity.INFO
    ),
    SystemCode.CONFIG_DATA: TranslationDef(
        "Profile Config '{key}': {value}", UISeverity.INFO
    ),
    SystemCode.CONFIG_SYNCED: TranslationDef(
        'Profile overrides cleared. Config is now synced with global settings.',
        UISeverity.INFO,
    ),
    SystemCode.UNKNOWN_COMMAND: TranslationDef('Unknown command.', UISeverity.ERROR),
    SystemCode.INIT_ERROR: TranslationDef('Initialization error.', UISeverity.ERROR),
    # CLI & Proxy Specific
    UiCode.ENTER_MASTER_PASSWORD: TranslationDef(
        f'{Theme.CYAN}Enter Master Password: {Theme.RESET}', UISeverity.INFO
    ),
    UiCode.DAEMON_STARTING: TranslationDef(
        "Starting daemon for profile '{profile}'...", UISeverity.INFO
    ),
    UiCode.DAEMON_ACTIVE: TranslationDef(
        f'Daemon active. Onion: {Theme.YELLOW}{{onion}}{Theme.RESET}.onion | IPC Port: {Theme.YELLOW}{{port}}{Theme.RESET}',
        UISeverity.INFO,
    ),
    UiCode.DAEMON_LOCKED_MODE: TranslationDef(
        'Daemon running in LOCKED mode... Waiting for IPC unlock.', UISeverity.INFO
    ),
    UiCode.DAEMON_REMOTE_NO_START: TranslationDef(
        'Cannot start a daemon on a remote profile!', UISeverity.ERROR
    ),
    UiCode.DAEMON_ALREADY_RUNNING: TranslationDef(
        "Daemon for profile '{profile}' is already running!", UISeverity.SYSTEM
    ),
    UiCode.DAEMON_EMPTY_PASSWORD: TranslationDef(
        'Master password cannot be empty.', UISeverity.ERROR
    ),
    UiCode.PURGE_WARNING: TranslationDef(
        f'{Theme.RED}You are about to PERMANENTLY wipe the entire Metor directory!{Theme.RESET}',
        UISeverity.SYSTEM,
    ),
    UiCode.PURGE_WARNING_REMOTE: TranslationDef(
        f'{Theme.RED}This includes all remote profiles and their data!{Theme.RESET}',
        UISeverity.SYSTEM,
    ),
    UiCode.PURGE_PROMPT: TranslationDef("Type 'yes' to proceed: ", UISeverity.INFO),
    UiCode.PURGE_ABORTED: TranslationDef('Purge aborted.', UISeverity.INFO),
    UiCode.PURGE_COMPLETE: TranslationDef(
        'Purge complete. All data destroyed.', UISeverity.INFO
    ),
    UiCode.CLEANUP_START: TranslationDef(
        'Cleaning up Metor processes and locks...', UISeverity.INFO
    ),
    UiCode.CLEANUP_COMPLETE: TranslationDef(
        'Killed {killed} Tor process(es) and cleared locks.', UISeverity.INFO
    ),
    UiCode.REMOTE_NUKE_WARNING: TranslationDef(
        f'{Theme.YELLOW}Data shredding may be ineffective on modern SSDs due to wear-leveling.{Theme.RESET}\n',
        UISeverity.INFO,
    ),
    UiCode.REMOTE_NUKE_SUCCESS: TranslationDef(
        "Remote daemon for profile '{profile}' nuked successfully.", UISeverity.INFO
    ),
    UiCode.REMOTE_NUKE_FAILED: TranslationDef(
        f'Failed to reach remote daemons for profiles: {Theme.CYAN}{{failed_remotes}}{Theme.RESET}',
        UISeverity.ERROR,
    ),
    UiCode.REMOTE_NUKE_OVERRIDE: TranslationDef(
        'You will lock yourself out of these remotes! Proceed with local wipe anyway? y/N: ',
        UISeverity.INFO,
    ),
    # Tor Subsystem
    NetworkCode.TOR_KEY_ERROR: TranslationDef(
        'Tor key error: {error}', UISeverity.ERROR
    ),
    NetworkCode.TOR_START_FAILED: TranslationDef(
        'Tor failed to start: {error}', UISeverity.ERROR
    ),
    NetworkCode.TOR_PROCESS_TERMINATED: TranslationDef(
        'Tor process terminated unexpectedly.', UISeverity.ERROR
    ),
    NetworkCode.ADDRESS_CURRENT: TranslationDef(
        "Current onion address for profile '{profile}': {onion}.onion", UISeverity.INFO
    ),
    NetworkCode.ADDRESS_GENERATED: TranslationDef(
        "New onion address generated for profile '{profile}': {onion}.onion",
        UISeverity.INFO,
    ),
    NetworkCode.ADDRESS_CANT_GENERATE_RUNNING: TranslationDef(
        "Changing the address for profile '{profile}' is not possible while a daemon is running.",
        UISeverity.ERROR,
    ),
    NetworkCode.ADDRESS_NOT_GENERATED: TranslationDef(
        "No onion address generated for profile '{profile}' yet. Simply start the daemon or use 'metor address generate'.",
        UISeverity.INFO,
    ),
    NetworkCode.RETUNNEL_FAILED: TranslationDef(
        'Failed to rotate Tor circuits: {error}', UISeverity.ERROR
    ),
    # IPC & Communication
    SystemCode.DAEMON_UNREACHABLE: TranslationDef(
        'Cannot reach remote Daemon on port {port}. Did you forget the SSH tunnel?',
        UISeverity.ERROR,
    ),
    SystemCode.DAEMON_OFFLINE: TranslationDef(
        'Local daemon is not running.', UISeverity.SYSTEM
    ),
    SystemCode.COMMAND_SUCCESS: TranslationDef(
        'Command executed successfully.', UISeverity.SYSTEM
    ),
    SystemCode.COMMUNICATION_FAILED: TranslationDef(
        'Failed to communicate with the daemon.', UISeverity.ERROR
    ),
    # Connections
    NetworkCode.CANNOT_CONNECT_SELF: TranslationDef(
        'You cannot connect to yourself.', UISeverity.SYSTEM
    ),
    NetworkCode.INVALID_TARGET: TranslationDef(
        "Invalid target: '{target}' not found or invalid.", UISeverity.ERROR
    ),
    NetworkCode.CANNOT_SWITCH_SELF: TranslationDef(
        'You cannot switch focus to yourself.', UISeverity.SYSTEM
    ),
    NetworkCode.NO_CONNECTION_TO_REJECT: TranslationDef(
        "No connection with '{alias}' to reject.", UISeverity.SYSTEM
    ),
    NetworkCode.NO_CONNECTION_TO_DISCONNECT: TranslationDef(
        "No active connection with '{alias}' to disconnect.", UISeverity.SYSTEM
    ),
    NetworkCode.NO_PENDING_CONNECTION: TranslationDef(
        "No pending connection from '{alias}' to accept.", UISeverity.SYSTEM
    ),
    NetworkCode.MAX_CONNECTIONS_REACHED: TranslationDef(
        "Cannot connect to '{target}'. Maximum concurrent connections ({max_conn}) reached.",
        UISeverity.ERROR,
    ),
    # Drops & Fallback
    NetworkCode.DROPS_DISABLED: TranslationDef(
        'Async offline messages are disabled by security policy.', UISeverity.SYSTEM
    ),
    NetworkCode.CANNOT_DROP_SELF: TranslationDef(
        'You cannot send offline drops to yourself.', UISeverity.SYSTEM
    ),
    NetworkCode.DROP_QUEUED: TranslationDef(
        "Message successfully queued for '{alias}'.", UISeverity.INFO
    ),
    NetworkCode.NO_PENDING_LIVE_MSGS: TranslationDef(
        "No pending live messages found for '{alias}'.", UISeverity.SYSTEM
    ),
    NetworkCode.FALLBACK_SUCCESS: TranslationDef(
        "Successfully converted {count} unacked message(s) to '{alias}' into drops.",
        UISeverity.INFO,
    ),
    NetworkCode.DAEMON_NOT_RUNNING_DROPS: TranslationDef(
        'The daemon must be running to send drops.', UISeverity.SYSTEM
    ),
    # Domain Transitions
    NetworkCode.CONNECTED: TranslationDef("Connected to '{alias}'.", UISeverity.INFO),
    NetworkCode.DISCONNECTED: TranslationDef(
        "Disconnected from '{alias}'.", UISeverity.INFO
    ),
    NetworkCode.INCOMING_CONNECTION: TranslationDef(
        f"Incoming connection from '{{alias}}'. Type '{Theme.GREEN}/accept {{alias}}{Theme.RESET}' or '{Theme.RED}/reject {{alias}}{Theme.RESET}'.",
        UISeverity.INFO,
    ),
    NetworkCode.CONNECTION_PENDING: TranslationDef(
        "Request sent to '{alias}'. Waiting for acceptance...", UISeverity.INFO
    ),
    NetworkCode.CONNECTION_AUTO_ACCEPTED: TranslationDef(
        "Pending request found. Auto-accepting connection with '{alias}'...",
        UISeverity.INFO,
    ),
    NetworkCode.CONNECTION_RETRY: TranslationDef(
        "Connecting to '{alias}' failed. Retrying ({attempt}/{max_retries})...",
        UISeverity.INFO,
    ),
    NetworkCode.CONNECTION_FAILED: TranslationDef(
        "Failed to connect to '{alias}'.", UISeverity.ERROR
    ),
    NetworkCode.CONNECTION_REJECTED: TranslationDef(
        "Connection with '{alias}' rejected.", UISeverity.INFO
    ),
    NetworkCode.INBOX_NOTIFICATION: TranslationDef(
        "Received {count} new offline message(s) from '{alias}'.", UISeverity.INFO
    ),
    # Advanced Network Resilience
    NetworkCode.CONNECTION_TIMEOUT: TranslationDef(
        "Connection with '{alias}' timed out.", UISeverity.SYSTEM
    ),
    NetworkCode.AUTO_RECONNECT_ATTEMPT: TranslationDef(
        "Attempting automatic reconnect to '{alias}'...", UISeverity.INFO
    ),
    NetworkCode.AUTO_RECONNECT_FAILED: TranslationDef(
        "Auto-reconnect to '{alias}' failed permanently.", UISeverity.ERROR
    ),
    NetworkCode.RETUNNEL_INITIATED: TranslationDef(
        "Initiating Tor circuit rotation and retunneling for '{alias}'...",
        UISeverity.SYSTEM,
    ),
    NetworkCode.RETUNNEL_SUCCESS: TranslationDef(
        "Successfully retunneled connection to '{alias}'.", UISeverity.INFO
    ),
    # Session
    UiCode.ALREADY_FOCUSED: TranslationDef(
        "Already focused on '{alias}'.", UISeverity.INFO
    ),
    UiCode.NO_ACTIVE_FOCUS: TranslationDef('No active focus.', UISeverity.SYSTEM),
    UiCode.FOCUS_SWITCHED: TranslationDef(
        "Switched focus to '{alias}'.", UISeverity.INFO
    ),
    UiCode.FOCUS_REMOVED: TranslationDef(
        "Removed focus from '{alias}'.", UISeverity.INFO
    ),
    # Contacts
    ContactCode.ALIAS_IN_USE: TranslationDef(
        "Alias '{alias}' is already in use.", UISeverity.SYSTEM
    ),
    ContactCode.ONION_IN_USE: TranslationDef(
        "The onion is already associated with saved contact '{alias}'.",
        UISeverity.SYSTEM,
    ),
    ContactCode.CONTACT_ADDED: TranslationDef(
        "Contact '{alias}' added successfully to profile '{profile}'.", UISeverity.INFO
    ),
    ContactCode.PEER_NOT_FOUND: TranslationDef(
        "Peer alias '{target}' not found.", UISeverity.ERROR
    ),
    ContactCode.CONTACT_ALREADY_SAVED: TranslationDef(
        "Alias '{alias}' is already saved.", UISeverity.SYSTEM
    ),
    ContactCode.PEER_PROMOTED: TranslationDef(
        "Discovered peer '{alias}' saved permanently to address book.", UISeverity.INFO
    ),
    ContactCode.ALIAS_SAME: TranslationDef(
        'The new alias must be different from the old one.', UISeverity.SYSTEM
    ),
    ContactCode.ALIAS_NOT_FOUND: TranslationDef(
        "Alias '{alias}' not found.", UISeverity.ERROR
    ),
    ContactCode.ALIAS_RENAMED: TranslationDef(
        "Alias renamed from '{old_alias}' to '{new_alias}'.", UISeverity.INFO
    ),
    ContactCode.PEER_CANT_DELETE_ACTIVE: TranslationDef(
        "Discovered peer '{alias}' cannot be deleted manually as it is tied to active states.",
        UISeverity.SYSTEM,
    ),
    ContactCode.CONTACT_DOWNGRADED: TranslationDef(
        "Contact '{alias}' is now unsaved.", UISeverity.INFO
    ),
    ContactCode.CONTACT_REMOVED_DOWNGRADED: TranslationDef(
        "Contact '{alias}' removed. Session downgraded to '{new_alias}'.",
        UISeverity.INFO,
    ),
    ContactCode.PEER_ANONYMIZED: TranslationDef(
        "Discovered peer '{alias}' anonymized to '{new_alias}'.", UISeverity.INFO
    ),
    ContactCode.CONTACT_REMOVED: TranslationDef(
        "Contact '{alias}' removed from profile '{profile}'.", UISeverity.INFO
    ),
    ContactCode.PEER_REMOVED: TranslationDef(
        "Discovered peer '{alias}' removed.", UISeverity.INFO
    ),
    ContactCode.CONTACTS_CLEARED: TranslationDef(
        "All contacts cleared and active peers anonymized for profile '{profile}'.",
        UISeverity.INFO,
    ),
    ContactCode.CONTACTS_CLEAR_FAILED: TranslationDef(
        'Failed to clear contacts.', UISeverity.ERROR
    ),
    ContactCode.RAM_ALIAS_REQUIRES_DAEMON: TranslationDef(
        'Daemon not running. Cannot save a RAM alias without an active session.',
        UISeverity.SYSTEM,
    ),
    # History & Messages
    DbCode.HISTORY_CLEARED: TranslationDef(
        "History for '{target}' cleared.", UISeverity.INFO
    ),
    DbCode.HISTORY_CLEARED_ALL: TranslationDef(
        "History for profile '{profile}' cleared.", UISeverity.INFO
    ),
    DbCode.HISTORY_CLEAR_FAILED: TranslationDef(
        'Failed to clear history.', UISeverity.ERROR
    ),
    DbCode.MESSAGES_CLEARED: TranslationDef(
        "All messages for '{target}' cleared.", UISeverity.INFO
    ),
    DbCode.MESSAGES_CLEARED_NON_CONTACTS: TranslationDef(
        "Messages for non-contact '{target}' cleared.", UISeverity.INFO
    ),
    DbCode.MESSAGES_CLEARED_ALL: TranslationDef(
        "All messages in profile '{profile}' cleared.", UISeverity.INFO
    ),
    DbCode.MESSAGES_CLEAR_FAILED: TranslationDef(
        'Failed to clear messages.', UISeverity.ERROR
    ),
    DbCode.NO_DB_FOUND: TranslationDef(
        "No database found for profile '{profile}'.", UISeverity.SYSTEM
    ),
    DbCode.DB_CLEARED: TranslationDef(
        "Database for profile '{profile}' successfully cleared.", UISeverity.INFO
    ),
    DbCode.DB_CLEAR_FAILED: TranslationDef(
        'Error clearing database.', UISeverity.ERROR
    ),
    # Profiles
    UiCode.INVALID_PROFILE_NAME: TranslationDef(
        'Invalid profile name.', UISeverity.ERROR
    ),
    UiCode.PROFILE_SET_DEFAULT: TranslationDef(
        "Default profile permanently set to '{profile}'.", UISeverity.INFO
    ),
    UiCode.REMOTE_REQUIRES_PORT: TranslationDef(
        'A remote profile requires a static port (--port <int>).', UISeverity.ERROR
    ),
    UiCode.PROFILE_EXISTS: TranslationDef(
        "Profile '{profile}' already exists.", UISeverity.SYSTEM
    ),
    UiCode.PROFILE_CREATED: TranslationDef(
        "Profile '{profile}' successfully created.", UISeverity.INFO
    ),
    UiCode.PROFILE_CREATED_PORT: TranslationDef(
        "{remote_tag}profile '{profile}' successfully created (Port {port}).",
        UISeverity.INFO,
    ),
    UiCode.PROFILE_NOT_FOUND: TranslationDef(
        "Profile '{profile}' does not exist.", UISeverity.ERROR
    ),
    UiCode.CANT_REMOVE_ACTIVE_PROFILE: TranslationDef(
        'Cannot remove active profile! Switch to another profile first.',
        UISeverity.SYSTEM,
    ),
    UiCode.CANT_REMOVE_DEFAULT_PROFILE: TranslationDef(
        'Cannot remove default profile! Change default first.', UISeverity.SYSTEM
    ),
    UiCode.DAEMON_RUNNING_CANT_REMOVE: TranslationDef(
        "Cannot remove profile '{profile}' while its daemon is running!",
        UISeverity.SYSTEM,
    ),
    UiCode.PROFILE_REMOVED: TranslationDef(
        "Profile '{profile}' successfully removed.", UISeverity.INFO
    ),
    UiCode.DAEMON_RUNNING_CANT_RENAME: TranslationDef(
        "Cannot rename profile '{old_profile}' while its daemon is running!",
        UISeverity.SYSTEM,
    ),
    UiCode.PROFILE_RENAMED: TranslationDef(
        "Profile '{old_profile}' successfully renamed to '{new_profile}'.",
        UISeverity.INFO,
    ),
    UiCode.DAEMON_RUNNING_CANT_CLEAR_DB: TranslationDef(
        "Cannot clear database for '{profile}' while daemon is running.",
        UISeverity.SYSTEM,
    ),
}


class Translator:
    """Provides dynamic text translations based on strict Translation Codes."""

    @staticmethod
    def get(
        code: DomainCode, params: Optional[Dict[str, JsonValue]] = None
    ) -> Tuple[str, UISeverity]:
        """
        Resolves a Translation Code to its localized string and generic severity type.
        Ensures the '{alias}' placeholder is passed through intact for the Renderer.

        Args:
            code (DomainCode): The rigid system code.
            params (Optional[Dict[str, JsonValue]]): Dynamic parameters to inject (e.g., attempt counts).

        Returns:
            Tuple[str, UISeverity]: The formatted text and its generic severity type.
        """
        entry: Optional[TranslationDef] = TRANSLATIONS.get(code)
        if not entry:
            return f'Unknown code: {code}', UISeverity.SYSTEM

        safe_params: Dict[str, JsonValue] = params.copy() if params else {}

        # Guard: Inject literal '{alias}' into kwargs to prevent KeyErrors during format()
        # and preserve the placeholder strictly for the Renderer.
        if 'alias' in safe_params and safe_params['alias']:
            safe_params['alias'] = '{alias}'

        try:
            text: str = entry.text.format(**safe_params)
            return text, entry.severity
        except Exception as e:
            return f'Translation error ({code}): {str(e)}', UISeverity.ERROR
