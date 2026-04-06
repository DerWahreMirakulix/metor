"""
Module providing a transparent proxy for all CLI commands.
Routes requests to the Daemon via IPC automatically, launching an ephemeral local runtime if offline.
Formats responses securely via the centralized Translator and Presenter using strict DTOs.
Enforces Domain-Driven Design by routing UI settings locally and Daemon settings via IPC.
Prevents structural ProfileConfigKey mutability vulnerabilities via strict property validations.
"""

import socket
import json
import dataclasses
import secrets
from typing import Optional, Dict, Union

from metor.application import run_with_headless_daemon
from metor.core.api import (
    AuthenticateSessionCommand,
    AuthRequiredEvent,
    EventType,
    JsonValue,
    IpcCommand,
    IpcEvent,
    InvalidPasswordEvent,
    UnlockCommand,
    SelfDestructCommand,
    SetSettingCommand,
    GetSettingCommand,
    SetConfigCommand,
    GetConfigCommand,
    SyncConfigCommand,
    GenerateAddressCommand,
    GetAddressCommand,
    SendDropCommand,
    ClearHistoryCommand,
    GetHistoryCommand,
    GetRawHistoryCommand,
    ClearMessagesCommand,
    GetMessagesCommand,
    MarkReadCommand,
    GetInboxCommand,
    GetContactsListCommand,
    AddContactCommand,
    RemoveContactCommand,
    RenameContactCommand,
    ClearContactsCommand,
    ClearProfileDbCommand,
    ContactsDataEvent,
    HistoryDataEvent,
    HistoryRawDataEvent,
    MessagesDataEvent,
    InboxCountsEvent,
    UnreadMessagesEvent,
    ProfilesDataEvent,
)
from metor.data.profile import ProfileManager, ProfileConfigKey
from metor.data.settings import Settings, SettingKey
from metor.ui import (
    PromptAbortedError,
    Theme,
    Translator,
    UIPresenter,
    prompt_hidden,
    prompt_session_auth_proof,
)
from metor.utils import Constants, TypeCaster


CLI_ASYNC_EVENT_TYPES: set[EventType] = {
    EventType.ACK,
    EventType.AUTO_RECONNECT_SCHEDULED,
    EventType.CONNECTED,
    EventType.CONNECTION_AUTO_ACCEPTED,
    EventType.CONNECTION_CONNECTING,
    EventType.CONNECTION_FAILED,
    EventType.CONNECTION_PENDING,
    EventType.CONNECTION_REJECTED,
    EventType.CONNECTION_RETRY,
    EventType.CONNECTIONS_STATE,
    EventType.CONTACT_REMOVED,
    EventType.DISCONNECTED,
    EventType.DROP_FAILED,
    EventType.FALLBACK_SUCCESS,
    EventType.INBOX_NOTIFICATION,
    EventType.INCOMING_CONNECTION,
    EventType.INIT,
    EventType.NO_PENDING_LIVE_MSGS,
    EventType.PENDING_CONNECTION_EXPIRED,
    EventType.REMOTE_MSG,
    EventType.RENAME_SUCCESS,
    EventType.RETUNNEL_FAILED,
    EventType.RETUNNEL_INITIATED,
    EventType.RETUNNEL_SUCCESS,
    EventType.SWITCH_SUCCESS,
}


class CliProxy:
    """Facade for CLI operations that either route locally or over strict IPC DTOs."""

    def __init__(self, pm: ProfileManager) -> None:
        """
        Initializes the CLI Proxy cleanly without instantiating any Database domains.

        Args:
            pm (ProfileManager): The active profile configuration.

        Returns:
            None
        """
        self._pm: ProfileManager = pm
        self.is_remote: bool = self._pm.is_remote()

    def _ensure_profile_exists(self) -> Optional[str]:
        """
        Guards against implicit directory creation for CLI operations.

        Args:
            None

        Returns:
            Optional[str]: Error message if profile doesn't exist, None otherwise.
        """
        if not self._pm.exists():
            return f"Profile '{self._pm.profile_name}' does not exist."
        return None

    def _translate_event(
        self,
        code: EventType,
        params: Optional[Dict[str, JsonValue]] = None,
    ) -> str:
        """
        Translates a strict daemon event to a fully formatted string for the CLI.
        Forces the resolution of {alias} since we are not in the dynamic rendering chat engine.

        Args:
            code (EventType): The strict daemon event identifier.
            params (Optional[Dict[str, JsonValue]]): The parameters.

        Returns:
            str: The fully formatted output string.
        """
        text, _ = Translator.get(code, params)

        if params and 'alias' in params and '{alias}' in text:
            text = text.replace('{alias}', str(params['alias']))
        elif '{alias}' in text:
            text = text.replace('{alias}', 'unknown')

        return text

    def _prefix_remote(self, text: str) -> str:
        """
        Prepends a [Remote] tag to output strings if operating via IPC on a remote profile.

        Args:
            text (str): The raw output string.

        Returns:
            str: The prefixed string.
        """
        if self.is_remote:
            return f'{Theme.PURPLE}[Remote]{Theme.RESET} {text}'
        return text

    def _prompt_password(
        self,
        prompt: str = 'Enter Master Password: ',
    ) -> Optional[str]:
        """
        Prompts interactively for one password and normalizes empty input to None.

        Args:
            prompt (str): The prompt text shown to the user.

        Returns:
            Optional[str]: The entered password, or None when empty.
        """
        password: str = prompt_hidden(f'{Theme.GREEN}{prompt}{Theme.RESET}')
        if not password:
            return None
        return password

    @staticmethod
    def _send_socket_command(sock: socket.socket, cmd: IpcCommand) -> None:
        """
        Serializes one typed IPC command onto an already connected socket.

        Args:
            sock (socket.socket): The connected IPC socket.
            cmd (IpcCommand): The outbound command DTO.

        Returns:
            None
        """
        sock.sendall((cmd.to_json() + '\n').encode('utf-8'))

    @staticmethod
    def _extract_session_auth_prompt(event: IpcEvent) -> Optional[tuple[str, str]]:
        """
        Extracts the daemon-issued session-auth challenge payload from one IPC event.

        Args:
            event (IpcEvent): The incoming IPC event.

        Returns:
            Optional[tuple[str, str]]: The challenge and salt, or None when unavailable.
        """
        if isinstance(event, (AuthRequiredEvent, InvalidPasswordEvent)):
            if event.challenge is not None and event.salt is not None:
                return event.challenge, event.salt

        return None

    def _read_socket_event(
        self,
        sock: socket.socket,
        buffer: bytearray,
    ) -> Optional[IpcEvent]:
        """
        Reads one strictly typed newline-delimited IPC event from the socket.

        Args:
            sock (socket.socket): The connected IPC socket.
            buffer (bytearray): The persistent receive buffer for the active socket.

        Returns:
            Optional[IpcEvent]: The decoded event, or None when the stream ends.
        """
        while b'\n' not in buffer:
            chunk: bytes = sock.recv(Constants.TCP_BUFFER_SIZE)
            if not chunk:
                return None

            buffer.extend(chunk)
            if len(buffer) > Constants.MAX_IPC_BYTES:
                raise ValueError('Daemon response exceeded the IPC size limit.')

        line_bytes, _, rest = buffer.partition(b'\n')
        buffer[:] = rest
        line: str = line_bytes.decode('utf-8')
        resp_dict: Dict[str, JsonValue] = json.loads(line)
        return IpcEvent.from_dict(resp_dict)

    def _format_ipc_event(self, event: IpcEvent) -> str:
        """
        Formats one typed IPC event for CLI output.

        Args:
            event (IpcEvent): The incoming daemon event DTO.

        Returns:
            str: The rendered CLI text.
        """
        if isinstance(
            event,
            (
                ContactsDataEvent,
                HistoryDataEvent,
                HistoryRawDataEvent,
                MessagesDataEvent,
                InboxCountsEvent,
                UnreadMessagesEvent,
                ProfilesDataEvent,
            ),
        ):
            text_fmt: str = UIPresenter.format_response(event, chat_mode=False)
            return self._prefix_remote(text_fmt)

        params_raw: Dict[str, object] = dataclasses.asdict(event)
        params: Dict[str, JsonValue] = {
            k: v
            for k, v in params_raw.items()
            if isinstance(v, (str, int, float, bool, type(None), list, dict))
        }
        text: str = self._translate_event(event.event_type, params)
        return self._prefix_remote(text)

    def _request_ipc(self, cmd: IpcCommand, wait_for_response: bool = True) -> str:
        """
        Helper to safely route IPC commands to the active Tor daemon or a temporary headless instance.
        Prompts for a password interactively if a headless database connection is required.

        Args:
            cmd (IpcCommand): The command to send.
            wait_for_response (bool): Whether to block and wait for a response.

        Returns:
            str: The translated response text or formatted DTO output.
        """
        try:
            port: Optional[int] = self._pm.get_daemon_port()

            if not port:
                if self.is_remote:
                    return self._prefix_remote(
                        f'Cannot reach remote Daemon on port '
                        f'{Theme.YELLOW}{self._pm.get_static_port()}{Theme.RESET}. '
                        'Did you forget the SSH tunnel?'
                    )

                password: Optional[str] = None
                if self._pm.supports_password_auth() and not isinstance(
                    cmd,
                    (
                        GetSettingCommand,
                        SetSettingCommand,
                        GetConfigCommand,
                        SetConfigCommand,
                        SyncConfigCommand,
                    ),
                ):
                    password = self._prompt_password()
                    if password is None:
                        return 'Master password cannot be empty.'

                return run_with_headless_daemon(
                    self._pm,
                    password,
                    lambda port: self._send_to_port(port, cmd, wait_for_response),
                )

            return self._send_to_port(port, cmd, wait_for_response)
        except PromptAbortedError:
            return self._prefix_remote('Aborted.')

    def _send_to_port(self, port: int, cmd: IpcCommand, wait_for_response: bool) -> str:
        """
        Executes the TCP socket transmission and cleanly parses the strictly-typed JSON response.
        Enforces buffer limits to avoid memory faults.

        Args:
            port (int): The target IPC socket port.
            cmd (IpcCommand): The outbound DTO.
            wait_for_response (bool): Waiting flag.

        Returns:
            str: Formatting terminal string output.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(self._pm.config.get_float(SettingKey.IPC_TIMEOUT))
                s.connect((Constants.LOCALHOST, port))
                self._send_socket_command(s, cmd)

                if not wait_for_response:
                    return self._prefix_remote('Command executed successfully.')

                buffer: bytearray = bytearray()
                pending_resume_event: Optional[EventType] = None
                auth_failures: int = 0
                unlock_failures: int = 0

                while True:
                    event: Optional[IpcEvent] = self._read_socket_event(s, buffer)
                    if event is None:
                        break

                    session_auth_prompt: Optional[tuple[str, str]] = (
                        self._extract_session_auth_prompt(event)
                    )

                    if event.event_type is EventType.AUTH_REQUIRED:
                        if session_auth_prompt is None:
                            return self._prefix_remote(
                                'Daemon session authentication challenge missing.'
                            )

                        proof: Optional[str] = prompt_session_auth_proof(
                            'Enter Master Password: ',
                            session_auth_prompt[0],
                            session_auth_prompt[1],
                        )
                        if proof is None:
                            return 'Master password cannot be empty.'

                        pending_resume_event = EventType.SESSION_AUTHENTICATED
                        self._send_socket_command(
                            s,
                            AuthenticateSessionCommand(proof=proof),
                        )
                        continue

                    if event.event_type is EventType.DAEMON_LOCKED:
                        password = self._prompt_password(
                            'Enter Master Password to unlock daemon: '
                        )
                        if password is None:
                            return 'Master password cannot be empty.'

                        pending_resume_event = EventType.DAEMON_UNLOCKED
                        self._send_socket_command(
                            s,
                            UnlockCommand(password=password),
                        )
                        continue

                    if event.event_type is EventType.INVALID_PASSWORD:
                        if pending_resume_event is EventType.SESSION_AUTHENTICATED:
                            auth_failures += 1
                            if auth_failures >= Constants.IPC_AUTH_FAILURE_LIMIT:
                                return self._format_ipc_event(event)

                            if session_auth_prompt is None:
                                return self._format_ipc_event(event)

                            proof = prompt_session_auth_proof(
                                'Enter Master Password: ',
                                session_auth_prompt[0],
                                session_auth_prompt[1],
                            )
                            if proof is None:
                                return 'Master password cannot be empty.'

                            self._send_socket_command(
                                s,
                                AuthenticateSessionCommand(proof=proof),
                            )
                            continue

                        if pending_resume_event is EventType.DAEMON_UNLOCKED:
                            unlock_failures += 1
                            if unlock_failures >= Constants.IPC_AUTH_FAILURE_LIMIT:
                                return self._format_ipc_event(event)

                            password = self._prompt_password(
                                'Enter Master Password to unlock daemon: '
                            )
                            if password is None:
                                return 'Master password cannot be empty.'

                            self._send_socket_command(
                                s,
                                UnlockCommand(password=password),
                            )
                            continue

                    if (
                        pending_resume_event is not None
                        and event.event_type is pending_resume_event
                    ):
                        pending_resume_event = None
                        self._send_socket_command(s, cmd)
                        continue

                    if event.event_type in CLI_ASYNC_EVENT_TYPES:
                        continue

                    return self._format_ipc_event(event)

            return self._prefix_remote('Command executed successfully.')
        except PromptAbortedError:
            return self._prefix_remote('Aborted.')
        except ValueError as exc:
            return self._prefix_remote(str(exc))
        except Exception:
            return self._prefix_remote('Failed to communicate with the daemon.')

    def unlock_daemon(self, password: Optional[str] = None) -> str:
        """
        Prompts for the master password and unlocks a daemon session.

        Args:
            password (Optional[str]): Optional injected password for non-interactive callers.

        Returns:
            str: Status message.
        """
        err: Optional[str] = self._ensure_profile_exists()
        if err:
            return err

        actual_password: Optional[str] = password
        if actual_password is None:
            try:
                actual_password = self._prompt_password()
            except PromptAbortedError:
                return self._prefix_remote('Aborted.')

        if not actual_password:
            return 'Master password cannot be empty.'
        return self._request_ipc(UnlockCommand(password=actual_password))

    def nuke_daemon(self) -> str:
        """
        Sends the self-destruct command to the daemon and waits for acknowledgment.

        Args:
            None

        Returns:
            str: Status message.
        """
        err: Optional[str] = self._ensure_profile_exists()
        if err:
            return err
        return self._request_ipc(SelfDestructCommand(), wait_for_response=True)

    def handle_settings_set(self, key: str, value: str) -> str:
        """
        Sets a global setting. Applies strictly to the global configuration.

        Args:
            key (str): The setting key.
            value (str): The new value.

        Returns:
            str: Status message.
        """
        try:
            key_enum: SettingKey = SettingKey(key)
        except ValueError:
            return self._translate_event(EventType.INVALID_SETTING_KEY)

        parsed_value: Union[str, int, float, bool] = TypeCaster.infer_from_string(value)

        if key_enum.is_ui:
            try:
                Settings.set(key_enum, parsed_value)
                return (
                    f"Global setting '{Theme.YELLOW}{key}{Theme.RESET}' updated "
                    'successfully.'
                )
            except (TypeError, ValueError) as exc:
                return self._translate_event(
                    EventType.SETTING_TYPE_ERROR,
                    {'key': key, 'reason': str(exc)},
                )

        return self._request_ipc(
            SetSettingCommand(setting_key=key, setting_value=parsed_value)
        )

    def handle_settings_get(self, key: str) -> str:
        """
        Retrieves a global setting.

        Args:
            key (str): The setting key.

        Returns:
            str: The formatted response containing the setting value.
        """
        try:
            key_enum: SettingKey = SettingKey(key)
        except ValueError:
            return self._translate_event(EventType.INVALID_SETTING_KEY)

        if key_enum.is_ui:
            val: str = Settings.get_str(key_enum)
            return (
                f"Global Setting '{Theme.YELLOW}{key}{Theme.RESET}': "
                f'{Theme.CYAN}{val}{Theme.RESET}'
            )

        return self._request_ipc(GetSettingCommand(setting_key=key))

    def handle_config_set(self, key: str, value: str) -> str:
        """
        Sets a profile-specific override configuration.
        Prevents modification of structural properties like 'is_remote'.

        Args:
            key (str): The config key.
            value (str): The new value.

        Returns:
            str: Status message.
        """
        if key == ProfileConfigKey.IS_REMOTE.value:
            return (
                f"The '{Theme.YELLOW}is_remote{Theme.RESET}' flag is immutable and "
                'cannot be changed after profile creation.'
            )

        try:
            key_enum: Union[SettingKey, ProfileConfigKey] = SettingKey(key)
        except ValueError:
            try:
                key_enum = ProfileConfigKey(key)
            except ValueError:
                return self._translate_event(EventType.INVALID_CONFIG_KEY)

        parsed_value: Union[str, int, float, bool] = TypeCaster.infer_from_string(value)

        # Allow local routing for pure UI settings AND ProfileConfigKey (like daemon_port)
        if isinstance(key_enum, ProfileConfigKey) or key_enum.is_ui:
            try:
                self._pm.config.set(key_enum, parsed_value)
                return (
                    f"Profile configuration override for '{Theme.YELLOW}{key}{Theme.RESET}' "
                    'updated successfully.'
                )
            except (TypeError, ValueError) as exc:
                return self._translate_event(
                    EventType.SETTING_TYPE_ERROR,
                    {'key': key, 'reason': str(exc)},
                )

        # Daemon-level settings go through IPC
        return self._request_ipc(
            SetConfigCommand(setting_key=key, setting_value=parsed_value)
        )

    def handle_config_get(self, key: str) -> str:
        """
        Retrieves the effective profile-specific configuration value (including global fallbacks).

        Args:
            key (str): The config key.

        Returns:
            str: The formatted response containing the config value.
        """
        try:
            key_enum: Union[SettingKey, ProfileConfigKey] = SettingKey(key)
        except ValueError:
            try:
                key_enum = ProfileConfigKey(key)
            except ValueError:
                return self._translate_event(EventType.INVALID_CONFIG_KEY)

        if isinstance(key_enum, ProfileConfigKey) or key_enum.is_ui:
            val: str = self._pm.config.get_str(key_enum)
            return (
                f"Profile Config '{Theme.YELLOW}{key}{Theme.RESET}': "
                f'{Theme.CYAN}{val}{Theme.RESET}'
            )

        return self._request_ipc(GetConfigCommand(setting_key=key))

    def handle_config_sync(self) -> str:
        """
        Wipes profile overrides to restore global defaults for the active profile.
        Syncs locally, and if a daemon is running or remote, propagates via IPC.

        Args:
            None

        Returns:
            str: Status message.
        """
        try:
            self._pm.config.sync_with_global()
            local_msg: str = (
                'Profile overrides cleared. Config is now synced with global settings.'
            )
        except Exception:
            return 'Failed to update profile config.'

        if self.is_remote or self._pm.is_daemon_running():
            daemon_msg: str = self._request_ipc(SyncConfigCommand())
            if self.is_remote:
                return f'{local_msg}\n{daemon_msg}'
            return daemon_msg

        return local_msg

    def get_address(self, generate: bool = False) -> str:
        """
        Retrieves or generates the hidden service address.

        Args:
            generate (bool): If True, requests the generation of a new address.

        Returns:
            str: The formatted onion address or an error message.
        """
        err: Optional[str] = self._ensure_profile_exists()
        if err:
            return err

        cmd: IpcCommand = GenerateAddressCommand() if generate else GetAddressCommand()
        return self._request_ipc(cmd)

    def send_drop(self, target_alias: str, text: str) -> str:
        """
        Queues an asynchronous offline message. Awaits the IPC response to provide non-generic status feedback.

        Args:
            target_alias (str): The destination alias.
            text (str): The message payload.

        Returns:
            str: Status message.
        """
        err: Optional[str] = self._ensure_profile_exists()
        if err:
            return err

        if not self.is_remote and not self._pm.is_daemon_running():
            return 'The daemon must be running to send drops.'

        return self._request_ipc(
            SendDropCommand(
                target=target_alias,
                text=text,
                msg_id=secrets.token_hex(Constants.UUID_MSG_BYTES),
            ),
            wait_for_response=True,
        )

    def get_history(
        self,
        target: Optional[str] = None,
        limit: Optional[int] = None,
        raw: bool = False,
    ) -> str:
        """
        Views the event history.

        Args:
            target (Optional[str]): The specific alias to filter by, if any.
            limit (Optional[int]): Maximum number of events to fetch.
            raw (bool): Whether to request the raw transport ledger.

        Returns:
            str: The formatted history output or a status message.
        """
        err: Optional[str] = self._ensure_profile_exists()
        if err:
            return err

        history_cmd = (
            GetRawHistoryCommand(target=target, limit=limit)
            if raw
            else GetHistoryCommand(target=target, limit=limit)
        )
        return self._request_ipc(history_cmd)

    def clear_history(self, target: Optional[str] = None) -> str:
        """
        Clears event history.

        Args:
            target (Optional[str]): The specific alias to clear, if any.

        Returns:
            str: The formatted status message.
        """
        err: Optional[str] = self._ensure_profile_exists()
        if err:
            return err

        return self._request_ipc(ClearHistoryCommand(target=target))

    def get_messages(
        self,
        target: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> str:
        """
        Views past messages.

        Args:
            target (Optional[str]): The specific alias to target.
            limit (Optional[int]): Maximum number of messages to fetch.

        Returns:
            str: The formatted message output or a status message.
        """
        err: Optional[str] = self._ensure_profile_exists()
        if err:
            return err

        return self._request_ipc(GetMessagesCommand(target=target, limit=limit))

    def clear_messages(
        self,
        target: Optional[str] = None,
        non_contacts_only: bool = False,
    ) -> str:
        """
        Clears stored messages.

        Args:
            target (Optional[str]): The specific alias to target.
            non_contacts_only (bool): Restrict clear operation to unsaved peers.

        Returns:
            str: The formatted status message.
        """
        err: Optional[str] = self._ensure_profile_exists()
        if err:
            return err

        return self._request_ipc(
            ClearMessagesCommand(target=target, non_contacts_only=non_contacts_only)
        )

    def handle_inbox(self, target: Optional[str] = None) -> str:
        """
        Views the inbox or reads unread messages locally.

        Args:
            target (Optional[str]): The specific alias to read from, if applicable.

        Returns:
            str: The formatted inbox or message strings.
        """
        err: Optional[str] = self._ensure_profile_exists()
        if err:
            return err

        cmd: IpcCommand = (
            MarkReadCommand(target=target) if target else GetInboxCommand()
        )
        return self._request_ipc(cmd)

    def contacts_list(self) -> str:
        """
        Lists contacts from the address book.

        Args:
            None

        Returns:
            str: Formatted list of contacts.
        """
        err: Optional[str] = self._ensure_profile_exists()
        if err:
            return err

        return self._request_ipc(GetContactsListCommand(chat_mode=False))

    def contacts_add(self, alias: str, onion: Optional[str] = None) -> str:
        """
        Adds a contact or promotes a discovered peer.

        Args:
            alias (str): The alias to add or promote.
            onion (Optional[str]): The optional onion address if adding a new contact manually.

        Returns:
            str: Status message.
        """
        err: Optional[str] = self._ensure_profile_exists()
        if err:
            return err

        return self._request_ipc(AddContactCommand(alias=alias, onion=onion))

    def contacts_rm(self, alias: str) -> str:
        """
        Removes a contact.

        Args:
            alias (str): The alias to remove.

        Returns:
            str: Status message.
        """
        err: Optional[str] = self._ensure_profile_exists()
        if err:
            return err

        return self._request_ipc(RemoveContactCommand(alias=alias))

    def contacts_rename(self, old: str, new: str) -> str:
        """
        Renames a contact.

        Args:
            old (str): The current alias.
            new (str): The new target alias.

        Returns:
            str: Status message.
        """
        err: Optional[str] = self._ensure_profile_exists()
        if err:
            return err

        return self._request_ipc(RenameContactCommand(old_alias=old, new_alias=new))

    def contacts_clear(self) -> str:
        """
        Clears the address book.

        Args:
            None

        Returns:
            str: Status message.
        """
        err: Optional[str] = self._ensure_profile_exists()
        if err:
            return err

        return self._request_ipc(ClearContactsCommand())

    def clear_profile_db(self) -> str:
        """
        Clears the SQLite database for the profile.

        Args:
            None

        Returns:
            str: Status message.
        """
        err: Optional[str] = self._ensure_profile_exists()
        if err:
            return err

        return self._request_ipc(ClearProfileDbCommand())
