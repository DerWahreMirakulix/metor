"""
Module managing the centralized UI translation and formatting registry.
Ensures the Daemon remains UI-agnostic by providing text resolutions locally.
Preserves the '{alias}' placeholder strictly for downstream dynamic rendering.
Utilizes domain-agnostic UISeverity Enums instead of Chat-specific routing types.
"""

from typing import Dict, Any, Tuple, Optional

from metor.core.api import TransCode

# Local Package Imports
from metor.ui.theme import Theme
from metor.ui.models import UISeverity, TranslationDef


TRANSLATIONS: Dict[TransCode, TranslationDef] = {
    # System / General
    TransCode.DAEMON_LOCKED: TranslationDef(
        'Daemon is locked. Please unlock first.', UISeverity.SYSTEM
    ),
    TransCode.DAEMON_UNLOCKED: TranslationDef(
        'Daemon unlocked successfully.', UISeverity.SYSTEM
    ),
    TransCode.AUTH_REQUIRED: TranslationDef(
        'Authentication required. Please unlock the session first.', UISeverity.SYSTEM
    ),
    TransCode.INVALID_PASSWORD: TranslationDef(
        'Invalid master password.', UISeverity.ERROR
    ),
    TransCode.ALREADY_UNLOCKED: TranslationDef(
        'Daemon is already unlocked.', UISeverity.SYSTEM
    ),
    TransCode.SESSION_AUTHENTICATED: TranslationDef(
        'Session authenticated successfully.', UISeverity.SYSTEM
    ),
    TransCode.SELF_DESTRUCT_INITIATED: TranslationDef(
        'Self-destruct command accepted. Nuking daemon...', UISeverity.SYSTEM
    ),
    TransCode.SETTING_UPDATED: TranslationDef(
        "Daemon setting '{key}' updated.", UISeverity.SYSTEM
    ),
    TransCode.SETTING_UPDATE_FAILED: TranslationDef(
        'Failed to update setting: {error}', UISeverity.ERROR
    ),
    TransCode.SETTING_TYPE_ERROR: TranslationDef(
        'Setting type error: {error}', UISeverity.ERROR
    ),
    # CLI & Proxy Specific
    TransCode.ENTER_MASTER_PASSWORD: TranslationDef(
        f'{Theme.CYAN}Enter Master Password: {Theme.RESET}', UISeverity.INFO
    ),
    TransCode.DAEMON_STARTING: TranslationDef(
        "Starting daemon for profile '{profile}'...", UISeverity.INFO
    ),
    TransCode.DAEMON_ACTIVE: TranslationDef(
        f'Daemon active. Onion: {Theme.YELLOW}{{onion}}{Theme.RESET}.onion | IPC Port: {Theme.YELLOW}{{port}}{Theme.RESET}',
        UISeverity.INFO,
    ),
    TransCode.DAEMON_LOCKED_MODE: TranslationDef(
        'Daemon running in LOCKED mode... Waiting for IPC unlock.', UISeverity.INFO
    ),
    TransCode.DAEMON_REMOTE_NO_START: TranslationDef(
        'Cannot start a daemon on a remote profile!', UISeverity.ERROR
    ),
    TransCode.DAEMON_ALREADY_RUNNING: TranslationDef(
        "Daemon for profile '{profile}' is already running!", UISeverity.SYSTEM
    ),
    TransCode.DAEMON_EMPTY_PASSWORD: TranslationDef(
        'Master password cannot be empty.', UISeverity.ERROR
    ),
    TransCode.PURGE_WARNING: TranslationDef(
        f'{Theme.RED}You are about to PERMANENTLY wipe the entire Metor directory!{Theme.RESET}',
        UISeverity.SYSTEM,
    ),
    TransCode.PURGE_WARNING_REMOTE: TranslationDef(
        f'{Theme.RED}This includes all remote profiles and their data!{Theme.RESET}',
        UISeverity.SYSTEM,
    ),
    TransCode.PURGE_PROMPT: TranslationDef("Type 'yes' to proceed: ", UISeverity.INFO),
    TransCode.PURGE_ABORTED: TranslationDef('Purge aborted.', UISeverity.INFO),
    TransCode.PURGE_COMPLETE: TranslationDef(
        'Purge complete. All data destroyed.', UISeverity.INFO
    ),
    TransCode.CLEANUP_START: TranslationDef(
        'Cleaning up Metor processes and locks...', UISeverity.INFO
    ),
    TransCode.CLEANUP_COMPLETE: TranslationDef(
        'Killed {killed} Tor process(es) and cleared locks.', UISeverity.INFO
    ),
    TransCode.REMOTE_NUKE_WARNING: TranslationDef(
        f'{Theme.YELLOW}Data shredding may be ineffective on modern SSDs due to wear-leveling.{Theme.RESET}\n',
        UISeverity.INFO,
    ),
    TransCode.REMOTE_NUKE_SUCCESS: TranslationDef(
        "Remote daemon for profile '{profile}' nuked successfully.", UISeverity.INFO
    ),
    TransCode.REMOTE_NUKE_FAILED: TranslationDef(
        f'Failed to reach remote daemons for profiles: {Theme.CYAN}{{failed_remotes}}{Theme.RESET}',
        UISeverity.ERROR,
    ),
    TransCode.REMOTE_NUKE_OVERRIDE: TranslationDef(
        'You will lock yourself out of these remotes! Proceed with local wipe anyway? y/N: ',
        UISeverity.INFO,
    ),
    TransCode.UNKNOWN_COMMAND: TranslationDef('Unknown command.', UISeverity.ERROR),
    # Tor Subsystem
    TransCode.TOR_KEY_ERROR: TranslationDef('Tor key error: {error}', UISeverity.ERROR),
    TransCode.TOR_START_FAILED: TranslationDef(
        'Tor failed to start: {error}', UISeverity.ERROR
    ),
    TransCode.TOR_PROCESS_TERMINATED: TranslationDef(
        'Tor process terminated unexpectedly.', UISeverity.ERROR
    ),
    TransCode.ADDRESS_CURRENT: TranslationDef(
        "Current onion address for profile '{profile}': {onion}.onion", UISeverity.INFO
    ),
    TransCode.ADDRESS_GENERATED: TranslationDef(
        "New onion address generated for profile '{profile}': {onion}.onion",
        UISeverity.INFO,
    ),
    TransCode.ADDRESS_CANT_GENERATE_RUNNING: TranslationDef(
        "Changing the address for profile '{profile}' is not possible while a daemon is running.",
        UISeverity.ERROR,
    ),
    TransCode.ADDRESS_NOT_GENERATED: TranslationDef(
        "No onion address generated for profile '{profile}' yet. Simply start the daemon or use 'metor address generate'.",
        UISeverity.INFO,
    ),
    TransCode.RETUNNEL_FAILED: TranslationDef(
        'Failed to rotate Tor circuits: {error}', UISeverity.ERROR
    ),
    # IPC & Communication
    TransCode.DAEMON_UNREACHABLE: TranslationDef(
        'Cannot reach remote Daemon on port {port}. Did you forget the SSH tunnel?',
        UISeverity.ERROR,
    ),
    TransCode.DAEMON_OFFLINE: TranslationDef(
        'Local daemon is not running.', UISeverity.SYSTEM
    ),
    TransCode.COMMAND_SUCCESS: TranslationDef(
        'Command executed successfully.', UISeverity.SYSTEM
    ),
    TransCode.COMMUNICATION_FAILED: TranslationDef(
        'Failed to communicate with the daemon.', UISeverity.ERROR
    ),
    # Connections
    TransCode.CANNOT_CONNECT_SELF: TranslationDef(
        'You cannot connect to yourself.', UISeverity.SYSTEM
    ),
    TransCode.INVALID_TARGET: TranslationDef(
        "Invalid target: '{target}' not found or invalid.", UISeverity.ERROR
    ),
    TransCode.CANNOT_SWITCH_SELF: TranslationDef(
        'You cannot switch focus to yourself.', UISeverity.SYSTEM
    ),
    TransCode.NO_CONNECTION_TO_REJECT: TranslationDef(
        "No connection with '{alias}' to reject.", UISeverity.SYSTEM
    ),
    TransCode.NO_CONNECTION_TO_DISCONNECT: TranslationDef(
        "No active connection with '{alias}' to disconnect.", UISeverity.SYSTEM
    ),
    TransCode.NO_PENDING_CONNECTION: TranslationDef(
        "No pending connection from '{alias}' to accept.", UISeverity.SYSTEM
    ),
    TransCode.MAX_CONNECTIONS_REACHED: TranslationDef(
        "Cannot connect to '{target}'. Maximum concurrent connections ({max_conn}) reached.",
        UISeverity.ERROR,
    ),
    # Drops & Fallback
    TransCode.DROPS_DISABLED: TranslationDef(
        'Async offline messages are disabled by security policy.', UISeverity.SYSTEM
    ),
    TransCode.CANNOT_DROP_SELF: TranslationDef(
        'You cannot send offline drops to yourself.', UISeverity.SYSTEM
    ),
    TransCode.DROP_QUEUED: TranslationDef(
        "Message successfully queued for '{alias}'.", UISeverity.INFO
    ),
    TransCode.NO_PENDING_LIVE_MSGS: TranslationDef(
        "No pending live messages found for '{alias}'.", UISeverity.SYSTEM
    ),
    TransCode.FALLBACK_SUCCESS: TranslationDef(
        "Successfully converted {count} unacked message(s) to '{alias}' into drops.",
        UISeverity.INFO,
    ),
    # Domain Transitions
    TransCode.CONNECTED: TranslationDef("Connected to '{alias}'.", UISeverity.INFO),
    TransCode.DISCONNECTED: TranslationDef(
        "Disconnected from '{alias}'.", UISeverity.INFO
    ),
    TransCode.INCOMING_CONNECTION: TranslationDef(
        f"Incoming connection from '{{alias}}'. Type '{Theme.GREEN}/accept {{alias}}{Theme.RESET}' or '{Theme.RED}/reject {{alias}}{Theme.RESET}'.",
        UISeverity.INFO,
    ),
    TransCode.CONNECTION_PENDING: TranslationDef(
        "Request sent to '{alias}'. Waiting for acceptance...", UISeverity.INFO
    ),
    TransCode.CONNECTION_AUTO_ACCEPTED: TranslationDef(
        "Pending request found. Auto-accepting connection with '{alias}'...",
        UISeverity.INFO,
    ),
    TransCode.CONNECTION_RETRY: TranslationDef(
        "Connecting to '{alias}' failed. Retrying ({attempt}/{max_retries})...",
        UISeverity.INFO,
    ),
    TransCode.CONNECTION_FAILED: TranslationDef(
        "Failed to connect to '{alias}'.", UISeverity.ERROR
    ),
    TransCode.CONNECTION_REJECTED: TranslationDef(
        "Connection with '{alias}' rejected.", UISeverity.INFO
    ),
    TransCode.INBOX_NOTIFICATION: TranslationDef(
        "Received {count} new offline message(s) from '{alias}'.", UISeverity.INFO
    ),
    # Advanced Network Resilience
    TransCode.CONNECTION_TIMEOUT: TranslationDef(
        "Connection with '{alias}' timed out.", UISeverity.SYSTEM
    ),
    TransCode.AUTO_RECONNECT_ATTEMPT: TranslationDef(
        "Attempting automatic reconnect to '{alias}'...", UISeverity.INFO
    ),
    TransCode.AUTO_RECONNECT_FAILED: TranslationDef(
        "Auto-reconnect to '{alias}' failed permanently.", UISeverity.ERROR
    ),
    TransCode.RETUNNEL_INITIATED: TranslationDef(
        "Initiating Tor circuit rotation and retunneling for '{alias}'...",
        UISeverity.SYSTEM,
    ),
    TransCode.RETUNNEL_SUCCESS: TranslationDef(
        "Successfully retunneled connection to '{alias}'.", UISeverity.INFO
    ),
    # Session
    TransCode.ALREADY_FOCUSED: TranslationDef(
        "Already focused on '{alias}'.", UISeverity.INFO
    ),
    TransCode.NO_ACTIVE_FOCUS: TranslationDef('No active focus.', UISeverity.SYSTEM),
    TransCode.FOCUS_SWITCHED: TranslationDef(
        "Switched focus to '{alias}'.", UISeverity.INFO
    ),
    TransCode.FOCUS_REMOVED: TranslationDef(
        "Removed focus from '{alias}'.", UISeverity.INFO
    ),
    # Contacts
    TransCode.ALIAS_IN_USE: TranslationDef(
        "Alias '{alias}' is already in use.", UISeverity.SYSTEM
    ),
    TransCode.ONION_IN_USE: TranslationDef(
        "The onion is already associated with saved contact '{alias}'.",
        UISeverity.SYSTEM,
    ),
    TransCode.CONTACT_ADDED: TranslationDef(
        "Contact '{alias}' added successfully to profile '{profile}'.", UISeverity.INFO
    ),
    TransCode.PEER_NOT_FOUND: TranslationDef(
        "Peer alias '{target}' not found.", UISeverity.ERROR
    ),
    TransCode.CONTACT_ALREADY_SAVED: TranslationDef(
        "Alias '{alias}' is already saved.", UISeverity.SYSTEM
    ),
    TransCode.PEER_PROMOTED: TranslationDef(
        "Discovered peer '{alias}' saved permanently to address book.", UISeverity.INFO
    ),
    TransCode.ALIAS_SAME: TranslationDef(
        'The new alias must be different from the old one.', UISeverity.SYSTEM
    ),
    TransCode.ALIAS_NOT_FOUND: TranslationDef(
        "Alias '{alias}' not found.", UISeverity.ERROR
    ),
    TransCode.ALIAS_RENAMED: TranslationDef(
        "Alias renamed from '{old_alias}' to '{new_alias}'.", UISeverity.INFO
    ),
    TransCode.PEER_CANT_DELETE_ACTIVE: TranslationDef(
        "Discovered peer '{alias}' cannot be deleted manually as it is tied to active states.",
        UISeverity.SYSTEM,
    ),
    TransCode.CONTACT_DOWNGRADED: TranslationDef(
        "Contact '{alias}' is now unsaved.", UISeverity.INFO
    ),
    TransCode.CONTACT_REMOVED_DOWNGRADED: TranslationDef(
        "Contact '{alias}' removed. Session downgraded to '{new_alias}'.",
        UISeverity.INFO,
    ),
    TransCode.PEER_ANONYMIZED: TranslationDef(
        "Discovered peer '{alias}' anonymized to '{new_alias}'.", UISeverity.INFO
    ),
    TransCode.CONTACT_REMOVED: TranslationDef(
        "Contact '{alias}' removed from profile '{profile}'.", UISeverity.INFO
    ),
    TransCode.PEER_REMOVED: TranslationDef(
        "Discovered peer '{alias}' removed.", UISeverity.INFO
    ),
    TransCode.CONTACTS_CLEARED: TranslationDef(
        "All contacts cleared and active peers anonymized for profile '{profile}'.",
        UISeverity.INFO,
    ),
    TransCode.CONTACTS_CLEAR_FAILED: TranslationDef(
        'Failed to clear contacts.', UISeverity.ERROR
    ),
    # History & Messages
    TransCode.HISTORY_CLEARED: TranslationDef(
        "History for '{target}' cleared.", UISeverity.INFO
    ),
    TransCode.HISTORY_CLEARED_ALL: TranslationDef(
        "History for profile '{profile}' cleared.", UISeverity.INFO
    ),
    TransCode.HISTORY_CLEAR_FAILED: TranslationDef(
        'Failed to clear history.', UISeverity.ERROR
    ),
    TransCode.MESSAGES_CLEARED: TranslationDef(
        "All messages for '{target}' cleared.", UISeverity.INFO
    ),
    TransCode.MESSAGES_CLEARED_NON_CONTACTS: TranslationDef(
        "Messages for non-contact '{target}' cleared.", UISeverity.INFO
    ),
    TransCode.MESSAGES_CLEARED_ALL: TranslationDef(
        "All messages in profile '{profile}' cleared.", UISeverity.INFO
    ),
    TransCode.MESSAGES_CLEAR_FAILED: TranslationDef(
        'Failed to clear messages.', UISeverity.ERROR
    ),
    # Profiles
    TransCode.INVALID_PROFILE_NAME: TranslationDef(
        'Invalid profile name.', UISeverity.ERROR
    ),
    TransCode.PROFILE_SET_DEFAULT: TranslationDef(
        "Default profile permanently set to '{profile}'.", UISeverity.INFO
    ),
    TransCode.REMOTE_REQUIRES_PORT: TranslationDef(
        'A remote profile requires a static port (--port <int>).', UISeverity.ERROR
    ),
    TransCode.PROFILE_EXISTS: TranslationDef(
        "Profile '{profile}' already exists.", UISeverity.SYSTEM
    ),
    TransCode.PROFILE_CREATED: TranslationDef(
        "Profile '{profile}' successfully created.", UISeverity.INFO
    ),
    TransCode.PROFILE_CREATED_PORT: TranslationDef(
        "{remote_tag}profile '{profile}' successfully created (Port {port}).",
        UISeverity.INFO,
    ),
    TransCode.PROFILE_NOT_FOUND: TranslationDef(
        "Profile '{profile}' does not exist.", UISeverity.ERROR
    ),
    TransCode.CANT_REMOVE_ACTIVE_PROFILE: TranslationDef(
        'Cannot remove active profile! Switch to another profile first.',
        UISeverity.SYSTEM,
    ),
    TransCode.CANT_REMOVE_DEFAULT_PROFILE: TranslationDef(
        'Cannot remove default profile! Change default first.', UISeverity.SYSTEM
    ),
    TransCode.DAEMON_RUNNING_CANT_REMOVE: TranslationDef(
        "Cannot remove profile '{profile}' while its daemon is running!",
        UISeverity.SYSTEM,
    ),
    TransCode.PROFILE_REMOVED: TranslationDef(
        "Profile '{profile}' successfully removed.", UISeverity.INFO
    ),
    TransCode.DAEMON_RUNNING_CANT_RENAME: TranslationDef(
        "Cannot rename profile '{old_profile}' while its daemon is running!",
        UISeverity.SYSTEM,
    ),
    TransCode.PROFILE_RENAMED: TranslationDef(
        "Profile '{old_profile}' successfully renamed to '{new_profile}'.",
        UISeverity.INFO,
    ),
    TransCode.DAEMON_RUNNING_CANT_CLEAR_DB: TranslationDef(
        "Cannot clear database for '{profile}' while daemon is running.",
        UISeverity.SYSTEM,
    ),
    TransCode.NO_DB_FOUND: TranslationDef(
        "No database found for profile '{profile}'.", UISeverity.SYSTEM
    ),
    TransCode.DB_CLEARED: TranslationDef(
        "Database for profile '{profile}' successfully cleared.", UISeverity.INFO
    ),
    TransCode.DB_CLEAR_FAILED: TranslationDef(
        'Error clearing database.', UISeverity.ERROR
    ),
    # Proxy
    TransCode.RAM_ALIAS_REQUIRES_DAEMON: TranslationDef(
        'Daemon not running. Cannot save a RAM alias without an active session.',
        UISeverity.SYSTEM,
    ),
    TransCode.INIT_ERROR: TranslationDef('Initialization error.', UISeverity.ERROR),
    TransCode.DAEMON_NOT_RUNNING_DROPS: TranslationDef(
        'The daemon must be running to send drops.', UISeverity.SYSTEM
    ),
}


class Translator:
    """Provides dynamic text translations based on strict Translation Codes."""

    @staticmethod
    def get(
        code: TransCode, params: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, UISeverity]:
        """
        Resolves a Translation Code to its localized string and generic severity type.
        Ensures the '{alias}' placeholder is passed through intact for the Renderer.

        Args:
            code (TransCode): The rigid system code.
            params (Optional[Dict[str, Any]]): Dynamic parameters to inject (e.g., attempt counts).

        Returns:
            Tuple[str, UISeverity]: The formatted text and its generic severity type.
        """
        entry: Optional[TranslationDef] = TRANSLATIONS.get(code)
        if not entry:
            return f'Unknown code: {code}', UISeverity.SYSTEM

        safe_params: Dict[str, Any] = params.copy() if params else {}

        # Guard: Inject literal '{alias}' into kwargs to prevent KeyErrors during format()
        # and preserve the placeholder strictly for the Renderer.
        if 'alias' in safe_params and safe_params['alias']:
            safe_params['alias'] = '{alias}'

        try:
            text: str = entry.text.format(**safe_params)
            return text, entry.severity
        except Exception as e:
            return f'Translation error ({code}): {str(e)}', UISeverity.ERROR
