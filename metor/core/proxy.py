"""
Module providing a transparent proxy for all CLI commands.
Routes requests to local SQLite managers or the Daemon via IPC automatically.
"""

import socket
import json
from typing import Optional, Dict, Any

from metor.data.profile import ProfileManager
from metor.data.settings import Settings, SettingKey
from metor.data.history import HistoryManager
from metor.data.contact import ContactManager
from metor.data.message import MessageManager
from metor.ui.theme import Theme
from metor.utils.constants import Constants

# Local Package Imports
from metor.core.api import IpcCommand, Action, IpcEvent
from metor.core.key import KeyManager
from metor.core.tor import TorManager


class CliProxy:
    """Facade for CLI operations, handling local vs. remote routing transparently."""

    def __init__(self, pm: ProfileManager) -> None:
        """
        Initializes the CLI Proxy.

        Args:
            pm (ProfileManager): The active profile configuration.
        """
        self._pm: ProfileManager = pm
        self.is_remote: bool = self._pm.is_remote()

        if not self.is_remote and not self._pm.is_daemon_running():
            self._km: Optional[KeyManager] = KeyManager(self._pm, None)
            self._hm: Optional[HistoryManager] = HistoryManager(self._pm, None)
            self._cm: Optional[ContactManager] = ContactManager(self._pm, None)
            self._mm: Optional[MessageManager] = MessageManager(self._pm, None)
        else:
            self._km = self._hm = self._cm = self._mm = None

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
                    event = IpcEvent.from_dict(resp_dict)
                    return self._prefix_remote(
                        event.text if event.text else 'Command executed successfully.'
                    )
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
        return self._request_ipc(IpcCommand(action=Action.UNLOCK, password=password))

    def nuke_daemon(self) -> str:
        """
        Sends the self-destruct command to the daemon and waits for acknowledgment.

        Returns:
            str: Status message.
        """
        return self._request_ipc(
            IpcCommand(action=Action.SELF_DESTRUCT), wait_for_response=True
        )

    def handle_settings(self, key: str, value: str) -> str:
        """
        Routes setting changes. Chat settings are applied locally; daemon settings via IPC.

        Args:
            key (str): The setting key string.
            value (str): The new value.

        Returns:
            str: Status message.
        """
        try:
            setting_enum = SettingKey(key)
        except ValueError:
            return f"Unknown setting key '{key}'."

        if setting_enum.value.startswith('chat.'):
            Settings.set(setting_enum, value)
            return f"Local chat setting '{key}' updated."

        return self._request_ipc(
            IpcCommand(action=Action.SET_SETTING, setting_key=key, setting_value=value)
        )

    def get_address(self, generate: bool = False) -> str:
        """Retrieves or generates the hidden service address."""
        if self.is_remote or self._pm.is_daemon_running():
            action = Action.GENERATE_ADDRESS if generate else Action.GET_ADDRESS
            return self._request_ipc(IpcCommand(action=action))

        if self._km:
            tm = TorManager(self._pm, self._km)
            _, msg = tm.generate_address() if generate else tm.get_address()
            return msg
        return 'Initialization error.'

    def send_drop(self, target_alias: str, text: str) -> str:
        """Queues an asynchronous offline message."""
        if not self.is_remote and not self._pm.is_daemon_running():
            return 'The daemon must be running to send drops.'

        cmd = IpcCommand(action=Action.SEND_DROP, target=target_alias, text=text)
        return self._request_ipc(cmd, wait_for_response=False)

    def handle_history(self, action: str, target: Optional[str] = None) -> str:
        """Views or clears the event history."""
        if self.is_remote or self._pm.is_daemon_running():
            act = Action.CLEAR_HISTORY if action == 'clear' else Action.GET_HISTORY
            return self._request_ipc(IpcCommand(action=act, target=target))

        if self._hm and self._cm:
            if action == 'clear':
                if target:
                    _, onion, exists = self._cm.resolve_target(target)
                    if not exists:
                        return f"Contact '{target}' not found."
                    _, msg = self._hm.clear_history(onion)
                    return msg
                _, msg = self._hm.clear_history()
                return msg
            return self._hm.show(self._cm, target)
        return 'Initialization error.'

    def handle_messages(
        self, action: str, target: Optional[str] = None, limit: int = 50
    ) -> str:
        """Views or clears past messages."""
        if self.is_remote or self._pm.is_daemon_running():
            act = Action.CLEAR_MESSAGES if action == 'clear' else Action.GET_MESSAGES
            return self._request_ipc(IpcCommand(action=act, target=target, limit=limit))

        if self._mm and self._cm:
            if action == 'clear':
                if target:
                    _, onion, exists = self._cm.resolve_target(target)
                    if not exists:
                        return f"Contact '{target}' not found."
                    _, msg = self._mm.clear_messages(onion)
                    return msg
                _, msg = self._mm.clear_messages()
                return msg
            return self._mm.show_history(target, self._cm, limit)
        return 'Initialization error.'

    def handle_inbox(self, action: str, target: Optional[str] = None) -> str:
        """Views the inbox or reads unread messages."""
        if self.is_remote or self._pm.is_daemon_running():
            act = Action.MARK_READ if action == 'read' else Action.GET_INBOX
            return self._request_ipc(IpcCommand(action=act, target=target))

        if self._mm and self._cm:
            if action == 'read':
                return self._mm.show_read(target, self._cm)
            return self._mm.show_inbox(self._cm)
        return 'Initialization error.'

    def contacts_list(self) -> str:
        """Lists contacts from the address book."""
        if self.is_remote or self._pm.is_daemon_running():
            return self._request_ipc(
                IpcCommand(action=Action.GET_CONTACTS_LIST, chat_mode=False)
            )
        if self._cm:
            return self._cm.show(chat_mode=False)
        return 'Initialization error.'

    def contacts_add(self, alias: str, onion: Optional[str] = None) -> str:
        """Adds a contact or promotes a RAM alias."""
        if self.is_remote or self._pm.is_daemon_running():
            return self._request_ipc(
                IpcCommand(action=Action.ADD_CONTACT, alias=alias, onion=onion),
                wait_for_response=False,
            )
        if not onion:
            return (
                'Daemon not running. Cannot save a RAM alias without an active session.'
            )
        if self._cm:
            _, msg = self._cm.add_contact(alias, onion)
            return msg
        return 'Initialization error.'

    def contacts_rm(self, alias: str) -> str:
        """Removes a contact."""
        if self.is_remote or self._pm.is_daemon_running():
            return self._request_ipc(
                IpcCommand(action=Action.REMOVE_CONTACT, alias=alias),
                wait_for_response=False,
            )
        if self._cm:
            _, msg = self._cm.remove_contact(alias)
            return msg
        return 'Initialization error.'

    def contacts_rename(self, old: str, new: str) -> str:
        """Renames a contact."""
        if self.is_remote or self._pm.is_daemon_running():
            return self._request_ipc(
                IpcCommand(action=Action.RENAME_CONTACT, old_alias=old, new_alias=new),
                wait_for_response=False,
            )
        if self._cm and self._hm:
            success, msg = self._cm.rename_contact(old, new)
            if success:
                self._hm.update_alias(old, new)
            return msg
        return 'Initialization error.'

    def contacts_clear(self) -> str:
        """Clears the address book."""
        if self.is_remote or self._pm.is_daemon_running():
            return self._request_ipc(IpcCommand(action=Action.CLEAR_CONTACTS))
        if self._cm:
            _, msg = self._cm.clear_contacts()
            return msg
        return 'Initialization error.'
