"""
Module defining the strict enumeration codes used across the IPC boundary.
Separated to prevent circular dependencies in payload definitions.
"""

from enum import Enum


class Action(str, Enum):
    """Enumeration of commands sent from the UI/CLI to the Daemon."""

    INIT = 'init'
    GET_CONNECTIONS = 'get_connections'
    GET_CONTACTS_LIST = 'get_contacts_list'
    CONNECT = 'connect'
    DISCONNECT = 'disconnect'
    ACCEPT = 'accept'
    REJECT = 'reject'
    MSG = 'msg'
    ADD_CONTACT = 'add_contact'
    REMOVE_CONTACT = 'remove_contact'
    RENAME_CONTACT = 'rename_contact'
    CLEAR_CONTACTS = 'clear_contacts'
    SWITCH = 'switch'

    SEND_DROP = 'send_drop'
    GET_INBOX = 'get_inbox'
    MARK_READ = 'mark_read'
    FALLBACK = 'fallback'

    GET_HISTORY = 'get_history'
    CLEAR_HISTORY = 'clear_history'
    GET_MESSAGES = 'get_messages'
    CLEAR_MESSAGES = 'clear_messages'
    GET_ADDRESS = 'get_address'
    GENERATE_ADDRESS = 'generate_address'
    CLEAR_PROFILE_DB = 'clear_profile_db'

    SET_SETTING = 'set_setting'
    SELF_DESTRUCT = 'self_destruct'
    UNLOCK = 'unlock'


class EventType(str, Enum):
    """Enumeration of events broadcasted by the Daemon to the connected UIs."""

    INIT = 'init'
    REMOTE_MSG = 'remote_msg'
    ACK = 'ack'
    CONNECTED = 'connected'
    DISCONNECTED = 'disconnected'
    RENAME_SUCCESS = 'rename_success'
    CONNECTIONS_STATE = 'connections_state'
    SWITCH_SUCCESS = 'switch_success'
    CONTACT_REMOVED = 'contact_removed'

    CONNECTION_PENDING = 'connection_pending'
    CONNECTION_AUTO_ACCEPTED = 'connection_auto_accepted'
    CONNECTION_RETRY = 'connection_retry'
    CONNECTION_FAILED = 'connection_failed'
    INCOMING_CONNECTION = 'incoming_connection'
    CONNECTION_REJECTED = 'connection_rejected'

    INBOX_NOTIFICATION = 'inbox_notification'
    INBOX_DATA = 'inbox_data'
    MSG_FALLBACK_TO_DROP = 'msg_fallback_to_drop'

    NOTIFICATION = 'notification'
    COMMAND_RESPONSE = 'command_response'


class TransCode(str, Enum):
    """Strict Domain Codes mapping generic backend events to local UI Translations."""

    GENERIC_MSG = 'generic_msg'

    # System / General
    DAEMON_LOCKED = 'daemon_locked'
    DAEMON_UNLOCKED = 'daemon_unlocked'
    AUTH_REQUIRED = 'auth_required'
    INVALID_PASSWORD = 'invalid_password'
    ALREADY_UNLOCKED = 'already_unlocked'
    SESSION_AUTHENTICATED = 'session_authenticated'
    SELF_DESTRUCT_INITIATED = 'self_destruct_initiated'
    SETTING_UPDATED = 'setting_updated'
    SETTING_UPDATE_FAILED = 'setting_update_failed'

    # IPC & Communication
    DAEMON_UNREACHABLE = 'daemon_unreachable'
    DAEMON_OFFLINE = 'daemon_offline'
    COMMAND_SUCCESS = 'command_success'
    COMMUNICATION_FAILED = 'communication_failed'

    # Connections
    CANNOT_CONNECT_SELF = 'cannot_connect_self'
    INVALID_TARGET = 'invalid_target'
    CANNOT_SWITCH_SELF = 'cannot_switch_self'
    NO_CONNECTION_TO_REJECT = 'no_connection_to_reject'
    NO_CONNECTION_TO_DISCONNECT = 'no_connection_to_disconnect'
    NO_PENDING_CONNECTION = 'no_pending_connection'

    # Drops
    DROPS_DISABLED = 'drops_disabled'
    CANNOT_DROP_SELF = 'cannot_drop_self'
    DROP_QUEUED = 'drop_queued'
    NO_PENDING_LIVE_MSGS = 'no_pending_live_msgs'
    FALLBACK_SUCCESS = 'fallback_success'

    # Domain Transitions (for UI formatting)
    CONNECTED = 'connected'
    DISCONNECTED = 'disconnected'
    INCOMING_CONNECTION = 'incoming_connection'
    CONNECTION_PENDING = 'connection_pending'
    CONNECTION_AUTO_ACCEPTED = 'connection_auto_accepted'
    CONNECTION_RETRY = 'connection_retry'
    CONNECTION_FAILED = 'connection_failed'
    CONNECTION_REJECTED = 'connection_rejected'
    INBOX_NOTIFICATION = 'inbox_notification'

    # Session
    ALREADY_FOCUSED = 'already_focused'
    NO_ACTIVE_FOCUS = 'no_active_focus'
    FOCUS_SWITCHED = 'focus_switched'
    FOCUS_REMOVED = 'focus_removed'

    # Contact Management
    ALIAS_IN_USE = 'alias_in_use'
    ONION_IN_USE = 'onion_in_use'
    CONTACT_ADDED = 'contact_added'
    PEER_NOT_FOUND = 'peer_not_found'
    CONTACT_ALREADY_SAVED = 'contact_already_saved'
    PEER_PROMOTED = 'peer_promoted'
    ALIAS_SAME = 'alias_same'
    ALIAS_NOT_FOUND = 'alias_not_found'
    ALIAS_RENAMED = 'alias_renamed'
    PEER_CANT_DELETE_ACTIVE = 'peer_cant_delete_active'
    CONTACT_DOWNGRADED = 'contact_downgraded'
    CONTACT_REMOVED_DOWNGRADED = 'contact_removed_downgraded'
    PEER_ANONYMIZED = 'peer_anonymized'
    CONTACT_REMOVED = 'contact_removed'
    PEER_REMOVED = 'peer_removed'
    CONTACTS_CLEARED = 'contacts_cleared'
    CONTACTS_CLEAR_FAILED = 'contacts_clear_failed'

    # History & Messages
    HISTORY_CLEARED = 'history_cleared'
    HISTORY_CLEARED_ALL = 'history_cleared_all'
    HISTORY_CLEAR_FAILED = 'history_clear_failed'
    MESSAGES_CLEARED = 'messages_cleared'
    MESSAGES_CLEARED_NON_CONTACTS = 'messages_cleared_non_contacts'
    MESSAGES_CLEARED_ALL = 'messages_cleared_all'
    MESSAGES_CLEAR_FAILED = 'messages_clear_failed'

    # Profiles
    INVALID_PROFILE_NAME = 'invalid_profile_name'
    PROFILE_SET_DEFAULT = 'profile_set_default'
    REMOTE_REQUIRES_PORT = 'remote_requires_port'
    PROFILE_EXISTS = 'profile_exists'
    PROFILE_CREATED = 'profile_created'
    PROFILE_CREATED_PORT = 'profile_created_port'
    PROFILE_NOT_FOUND = 'profile_not_found'
    CANT_REMOVE_ACTIVE_PROFILE = 'cant_remove_active_profile'
    CANT_REMOVE_DEFAULT_PROFILE = 'cant_remove_default_profile'
    DAEMON_RUNNING_CANT_REMOVE = 'daemon_running_cant_remove'
    PROFILE_REMOVED = 'profile_removed'
    DAEMON_RUNNING_CANT_RENAME = 'daemon_running_cant_rename'
    PROFILE_RENAMED = 'profile_renamed'
    DAEMON_RUNNING_CANT_CLEAR_DB = 'daemon_running_cant_clear_db'
    NO_DB_FOUND = 'no_db_found'
    DB_CLEARED = 'db_cleared'
    DB_CLEAR_FAILED = 'db_clear_failed'

    # Proxy Exceptions
    RAM_ALIAS_REQUIRES_DAEMON = 'ram_alias_requires_daemon'
    INIT_ERROR = 'init_error'
    DAEMON_NOT_RUNNING_DROPS = 'daemon_not_running_drops'
