"""
Module providing a transparent proxy for all CLI commands.
Routes requests to the Daemon via IPC automatically, launching a HeadlessDaemon if offline.
Formats responses securely via the centralized Translator and Presenter using strict DTOs.
Enforces Domain-Driven Design by removing direct SQLite database access from the UI Layer.
"""

import socket
import json
import getpass
import dataclasses
from typing import Any, Optional, Dict, Union

from metor.core.api import (
    JsonValue,
    IpcCommand,
    IpcEvent,
    TransCode,
    UnlockCommand,
    SelfDestructCommand,
    SetSettingCommand,
    GenerateAddressCommand,
    GetAddressCommand,
    SendDropCommand,
    ClearHistoryCommand,
    GetHistoryCommand,
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
    MessagesDataEvent,
    InboxCountsEvent,
    UnreadMessagesEvent,
    ProfilesDataEvent,
)
from metor.core.daemon import HeadlessDaemon
from metor.data import Settings, SettingKey
from metor.data.profile import ProfileManager
from metor.ui import Theme, UIPresenter, Translator
from metor.utils import Constants


class CliProxy:
    """Facade for CLI operations, strictly interacting via IPC events and DTOs only."""

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
            return self._translate_local(
                TransCode.PROFILE_NOT_FOUND, {'profile': self._pm.profile_name}
            )
        return None

    def _translate_local(
        self, code: TransCode, params: Optional[Dict[str, JsonValue]] = None
    ) -> str:
        """
        Translates a TransCode to a fully formatted string specifically for the CLI.
        Forces the resolution of {alias} since we are not in the dynamic rendering chat engine.

        Args:
            code (TransCode): The strict domain code.
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
        port: Optional[int] = self._pm.get_daemon_port()

        if not port:
            if self.is_remote:
                return self._prefix_remote(
                    self._translate_local(
                        TransCode.DAEMON_UNREACHABLE,
                        {'port': str(self._pm.get_static_port())},
                    )
                )

            # Offline local state: Route through ephemeral HeadlessDaemon to enforce DDD
            password: Optional[str] = None
            if not isinstance(cmd, (GetAddressCommand, GenerateAddressCommand)):
                prompt, _ = Translator.get(TransCode.ENTER_MASTER_PASSWORD)
                password = getpass.getpass(prompt)

            with HeadlessDaemon(self._pm, password) as hd:
                return self._send_to_port(hd.port, cmd, wait_for_response)

        # Active local or SSH remote tunnel
        return self._send_to_port(port, cmd, wait_for_response)

    def _send_to_port(self, port: int, cmd: IpcCommand, wait_for_response: bool) -> str:
        """
        Executes the TCP socket transmission and cleanly parses the strictly-typed JSON response.

        Args:
            port (int): The target IPC socket port.
            cmd (IpcCommand): The outbound DTO.
            wait_for_response (bool): Waiting flag.

        Returns:
            str: Formatting terminal string output.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect((Constants.LOCALHOST, port))
                s.sendall((cmd.to_json() + '\n').encode('utf-8'))

                if not wait_for_response:
                    return self._prefix_remote(
                        self._translate_local(TransCode.COMMAND_SUCCESS)
                    )

                buffer: str = ''
                while True:
                    chunk: bytes = s.recv(4096)
                    if not chunk:
                        break
                    buffer += chunk.decode('utf-8')
                    if '\n' in buffer:
                        break

            if buffer:
                resp_dict: Dict[str, JsonValue] = json.loads(buffer.split('\n')[0])
                event: IpcEvent = IpcEvent.from_dict(resp_dict)

                if isinstance(
                    event,
                    (
                        ContactsDataEvent,
                        HistoryDataEvent,
                        MessagesDataEvent,
                        InboxCountsEvent,
                        UnreadMessagesEvent,
                        ProfilesDataEvent,
                    ),
                ):
                    text_fmt: str = UIPresenter.format_response(event, chat_mode=False)
                    return self._prefix_remote(text_fmt)

                # For generic Success, Error, or Notification DTOs
                params_raw: Dict[str, Any] = dataclasses.asdict(event)
                params: Dict[str, JsonValue] = {
                    k: v
                    for k, v in params_raw.items()
                    if isinstance(v, (str, int, float, bool, type(None)))
                }
                code: TransCode = getattr(event, 'code', TransCode.COMMAND_SUCCESS)
                text: str = self._translate_local(code, params)
                return self._prefix_remote(text)

            return self._prefix_remote(self._translate_local(TransCode.COMMAND_SUCCESS))
        except Exception:
            return self._prefix_remote(
                self._translate_local(TransCode.COMMUNICATION_FAILED)
            )

    def unlock_daemon(self, password: str) -> str:
        """
        Sends the master password to unlock a remote daemon.

        Args:
            password (str): The master password.

        Returns:
            str: Status message.
        """
        err: Optional[str] = self._ensure_profile_exists()
        if err:
            return err
        return self._request_ipc(UnlockCommand(password=password))

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

    def _parse_setting_value(self, value: str) -> Union[str, int, float, bool]:
        """
        Converts raw CLI string input into native Python types for clean persistence.

        Args:
            value (str): The string value from sys.argv.

        Returns:
            Union[str, int, float, bool]: The correctly typed value.
        """
        val_lower: str = value.lower()
        if val_lower == 'true':
            return True
        if val_lower == 'false':
            return False

        if value.isdigit() or (value.startswith('-') and value[1:].isdigit()):
            return int(value)

        try:
            return float(value)
        except ValueError:
            return value

    def handle_settings(self, key: str, value: str) -> str:
        """
        Routes setting changes. UI settings are applied locally. Daemon settings are
        routed via IPC if running, or applied locally if the daemon is offline.
        Enforces strict native typing is maintained.

        Args:
            key (str): The setting key string.
            value (str): The new value.

        Returns:
            str: Status message.
        """
        try:
            setting_enum: SettingKey = SettingKey(key)
        except ValueError:
            return f"Unknown setting key '{key}'."

        parsed_value: Union[str, int, float, bool] = self._parse_setting_value(value)

        if setting_enum.value.startswith('ui.'):
            try:
                Settings.set(setting_enum, parsed_value)
                return self._translate_local(TransCode.SETTING_UPDATED, {'key': key})
            except TypeError as e:
                return str(e)

        if self.is_remote or self._pm.is_daemon_running():
            return self._request_ipc(
                SetSettingCommand(setting_key=key, setting_value=parsed_value)
            )

        try:
            Settings.set(setting_enum, parsed_value)
            return self._translate_local(TransCode.SETTING_UPDATED, {'key': key})
        except TypeError as e:
            return str(e)

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
            return self._translate_local(TransCode.DAEMON_NOT_RUNNING_DROPS)

        return self._request_ipc(
            SendDropCommand(target=target_alias, text=text, cli_mode=True),
            wait_for_response=True,
        )

    def handle_history(
        self, action: str, target: Optional[str] = None, limit: Optional[int] = None
    ) -> str:
        """
        Views or clears the event history.

        Args:
            action (str): The action to perform ('show' or 'clear').
            target (Optional[str]): The specific alias to filter by, if any.
            limit (Optional[int]): Maximum number of events to fetch.

        Returns:
            str: The formatted history output or a status message.
        """
        err: Optional[str] = self._ensure_profile_exists()
        if err:
            return err

        cmd: IpcCommand = (
            ClearHistoryCommand(target=target)
            if action == 'clear'
            else GetHistoryCommand(target=target, limit=limit)
        )
        return self._request_ipc(cmd)

    def handle_messages(
        self,
        action: str,
        target: Optional[str] = None,
        limit: Optional[int] = None,
        non_contacts_only: bool = False,
    ) -> str:
        """
        Views or clears past messages.

        Args:
            action (str): The action to perform ('show' or 'clear').
            target (Optional[str]): The specific alias to target.
            limit (Optional[int]): Maximum number of messages to fetch.
            non_contacts_only (bool): Restrict clear operation to unsaved peers.

        Returns:
            str: The formatted message output or a status message.
        """
        err: Optional[str] = self._ensure_profile_exists()
        if err:
            return err

        cmd: IpcCommand = (
            ClearMessagesCommand(target=target, non_contacts_only=non_contacts_only)
            if action == 'clear'
            else GetMessagesCommand(target=target, limit=limit)
        )
        return self._request_ipc(cmd)

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
            MarkReadCommand(target=target, cli_mode=True)
            if target
            else GetInboxCommand(cli_mode=True)
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
        Adds a contact or promotes a RAM alias.

        Args:
            alias (str): The alias to add or promote.
            onion (Optional[str]): The optional onion address if adding a new contact manually.

        Returns:
            str: Status message.
        """
        err: Optional[str] = self._ensure_profile_exists()
        if err:
            return err

        if not self.is_remote and not self._pm.is_daemon_running() and not onion:
            return self._translate_local(TransCode.RAM_ALIAS_REQUIRES_DAEMON)

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
