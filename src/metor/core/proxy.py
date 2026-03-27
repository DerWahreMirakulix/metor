"""
Module providing a transparent proxy for all CLI commands.
Routes requests to local SQLite managers or the Daemon via IPC automatically.
"""

import socket
import json
from typing import Optional, Dict, Any, Union

from metor.data.profile import ProfileManager
from metor.data.settings import Settings, SettingKey
from metor.data.history import HistoryManager
from metor.data.contact import ContactManager
from metor.data.message import MessageManager
from metor.ui.theme import Theme
from metor.utils.constants import Constants

# Local Package Imports
from metor.core.api import (
    IpcCommand,
    IpcEvent,
    CliResponseEvent,
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
)
from metor.core.key import KeyManager
from metor.core.tor import TorManager


class CliProxy:
    """Facade for CLI operations, handling local vs. remote routing transparently."""

    def __init__(self, pm: ProfileManager) -> None:
        """
        Initializes the CLI Proxy.
        Only initializes database managers if the profile physically exists on disk.

        Args:
            pm (ProfileManager): The active profile configuration.

        Returns:
            None
        """
        self._pm: ProfileManager = pm
        self.is_remote: bool = self._pm.is_remote()

        if (
            not self.is_remote
            and not self._pm.is_daemon_running()
            and self._pm.exists()
        ):
            self._km: Optional[KeyManager] = KeyManager(self._pm, None)
            self._hm: Optional[HistoryManager] = HistoryManager(self._pm, None)
            self._cm: Optional[ContactManager] = ContactManager(self._pm, None)
            self._mm: Optional[MessageManager] = MessageManager(self._pm, None)
        else:
            self._km = self._hm = self._cm = self._mm = None

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
        Helper to send IPC commands (Local or via SSH Tunnel).

        Args:
            cmd (IpcCommand): The command to send.
            wait_for_response (bool): Whether to block and wait for a response.

        Returns:
            str: The response text or error message.
        """
        port: Optional[int] = self._pm.get_daemon_port()
        if not port:
            if self.is_remote:
                return self._prefix_remote(
                    f'Cannot reach remote Daemon on port {self._pm.get_static_port()}. Did you forget the SSH tunnel?'
                )
            return 'Local daemon is not running.'

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect((Constants.LOCALHOST, port))
                s.sendall((cmd.to_json() + '\n').encode('utf-8'))

                if not wait_for_response:
                    return self._prefix_remote('Command successfully sent to daemon.')

                buffer: str = ''
                while True:
                    chunk: bytes = s.recv(4096)
                    if not chunk:
                        break
                    buffer += chunk.decode('utf-8')
                    if '\n' in buffer:
                        break

                if buffer:
                    resp_dict: Dict[str, Any] = json.loads(buffer.split('\n')[0])
                    event: IpcEvent = IpcEvent.from_dict(resp_dict)

                    text = getattr(event, 'text', None)
                    if text:
                        alias = getattr(event, 'alias', None)
                        if alias and '{alias}' in text:
                            text = text.replace('{alias}', alias)
                        return self._prefix_remote(text)

                    return self._prefix_remote('Command executed successfully.')
        except Exception:
            pass
        return self._prefix_remote('Failed to communicate with the daemon.')

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
                return f"Local UI setting '{key}' updated."
            except TypeError as e:
                return str(e)

        if self.is_remote or self._pm.is_daemon_running():
            return self._request_ipc(
                SetSettingCommand(setting_key=key, setting_value=parsed_value)
            )

        # Local daemon is offline, write directly to file
        try:
            Settings.set(setting_enum, parsed_value)
            return f"Offline daemon setting '{key}' updated locally."
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

        if self.is_remote or self._pm.is_daemon_running():
            cmd: IpcCommand = (
                GenerateAddressCommand() if generate else GetAddressCommand()
            )
            return self._request_ipc(cmd)

        if self._km:
            tm: TorManager = TorManager(self._pm, self._km)
            _, msg = tm.generate_address() if generate else tm.get_address()
            return msg
        return 'Initialization error.'

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

        if self.is_remote or self._pm.is_daemon_running():
            cmd: IpcCommand = (
                ClearHistoryCommand(target=target)
                if action == 'clear'
                else GetHistoryCommand(target=target, limit=limit)
            )
            return self._request_ipc(cmd)

        if self._hm and self._cm:
            if action == 'clear':
                if target:
                    _, onion, exists = self._cm.resolve_target(target)
                    if not exists:
                        return f"Contact '{target}' not found."
                    _, msg = self._hm.clear_history(onion)
                    self._cm.cleanup_orphans([])
                    return msg
                _, msg = self._hm.clear_history()
                self._cm.cleanup_orphans([])
                return msg
            return self._hm.show(self._cm, target, limit)
        return 'Initialization error.'

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

        if self.is_remote or self._pm.is_daemon_running():
            cmd: IpcCommand = (
                ClearMessagesCommand(target=target, non_contacts_only=non_contacts_only)
                if action == 'clear'
                else GetMessagesCommand(target=target, limit=limit)
            )
            return self._request_ipc(cmd)

        if self._mm and self._cm:
            if action == 'clear':
                if target:
                    _, onion, exists = self._cm.resolve_target(target)
                    if not exists:
                        return f"Contact '{target}' not found."
                    _, msg = self._mm.clear_messages(onion, non_contacts_only)
                    self._cm.cleanup_orphans([])
                    return msg
                _, msg = self._mm.clear_messages(None, non_contacts_only)
                self._cm.cleanup_orphans([])
                return msg
            return self._mm.show_history(target, self._cm, limit)
        return 'Initialization error.'

    def handle_inbox(self, target: Optional[str] = None) -> str:
        """
        Views the inbox or reads unread messages. Forces the Daemon to format locally for CLI.

        Args:
            target (Optional[str]): The specific alias to read from, if applicable.

        Returns:
            str: The formatted inbox or message strings.
        """
        err: Optional[str] = self._ensure_profile_exists()
        if err:
            return err

        if self.is_remote or self._pm.is_daemon_running():
            cmd: IpcCommand = (
                MarkReadCommand(target=target, cli_mode=True)
                if target
                else GetInboxCommand(cli_mode=True)
            )
            return self._request_ipc(cmd)

        if self._mm and self._cm:
            if target:
                return self._mm.show_read(target, self._cm)
            return self._mm.show_inbox(self._cm)
        return 'Initialization error.'

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

        if self.is_remote or self._pm.is_daemon_running():
            return self._request_ipc(GetContactsListCommand(chat_mode=False))
        if self._cm:
            return self._cm.show(chat_mode=False)
        return 'Initialization error.'

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

        if self.is_remote or self._pm.is_daemon_running():
            return self._request_ipc(AddContactCommand(alias=alias, onion=onion))
        if not onion:
            return (
                'Daemon not running. Cannot save a RAM alias without an active session.'
            )
        if self._cm:
            _, msg = self._cm.add_contact(alias, onion)
            return msg
        return 'Initialization error.'

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

        if self.is_remote or self._pm.is_daemon_running():
            return self._request_ipc(RemoveContactCommand(alias=alias))
        if self._cm:
            _, msg, _, _ = self._cm.remove_contact(alias, active_onions=[])
            self._cm.cleanup_orphans([])
            return msg
        return 'Initialization error.'

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

        if self.is_remote or self._pm.is_daemon_running():
            return self._request_ipc(RenameContactCommand(old_alias=old, new_alias=new))
        if self._cm and self._hm:
            success, msg = self._cm.rename_contact(old, new)
            return msg
        return 'Initialization error.'

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

        if self.is_remote or self._pm.is_daemon_running():
            return self._request_ipc(ClearContactsCommand())
        if self._cm:
            _, msg, _, _ = self._cm.clear_contacts(active_onions=[])
            self._cm.cleanup_orphans([])
            return msg
        return 'Initialization error.'

    def clear_profile_db(self) -> str:
        """
        Clears the SQLite database for the profile (routes via IPC if remote or running).

        Args:
            None

        Returns:
            str: Status message.
        """
        err: Optional[str] = self._ensure_profile_exists()
        if err:
            return err

        if self.is_remote or self._pm.is_daemon_running():
            return self._request_ipc(ClearProfileDbCommand())

        _, msg = ProfileManager.clear_profile_db(self._pm.profile_name)
        return msg
