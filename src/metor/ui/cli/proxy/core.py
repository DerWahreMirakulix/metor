"""Facade for CLI operations that either route locally or over strict IPC DTOs."""

import secrets
import socket
from typing import Dict, Optional

from metor.core.api import (
    AddContactCommand,
    ClearContactsCommand,
    ClearHistoryCommand,
    ClearMessagesCommand,
    ClearProfileDbCommand,
    EventType,
    GenerateAddressCommand,
    GetAddressCommand,
    GetContactsListCommand,
    GetHistoryCommand,
    GetInboxCommand,
    GetMessagesCommand,
    GetRawHistoryCommand,
    IpcCommand,
    JsonValue,
    MarkReadCommand,
    RemoveContactCommand,
    RenameContactCommand,
    SendDropCommand,
    SelfDestructCommand,
    UnlockCommand,
)
from metor.data.profile import ProfileManager, ProfileSecurityMode
from metor.ui import (
    PromptAbortedError,
    Theme,
    Translator,
    prompt_hidden,
)
from metor.ui.cli.proxy.profiles import CliProxyProfileActions
from metor.ui.cli.proxy.rendering import CliProxyEventRenderer
from metor.ui.cli.proxy.settings import CliProxySettingsActions
from metor.ui.cli.proxy.transport import CliProxyTransport
from metor.utils import Constants


class CliProxy:
    """Facade for CLI operations that either route locally or over strict IPC DTOs."""

    def __init__(self, pm: ProfileManager) -> None:
        """
        Initializes the CLI proxy facade.

        Args:
            pm (ProfileManager): The active profile configuration.

        Returns:
            None
        """
        self._pm: ProfileManager = pm
        self.is_remote: bool = self._pm.is_remote()

        self._renderer: CliProxyEventRenderer = CliProxyEventRenderer(
            translate_event=self._translate_event,
            prefix_remote=self._prefix_remote,
        )
        self._transport: CliProxyTransport = CliProxyTransport(
            self._pm,
            is_remote=self.is_remote,
            prompt_password=self._prompt_password,
            prefix_remote=self._prefix_remote,
            format_event=lambda event, prefix_remote=True: (
                self._renderer.format_ipc_event(
                    event,
                    prefix_remote=prefix_remote,
                )
            ),
            send_socket_command=self._send_socket_command,
        )
        self._settings: CliProxySettingsActions = CliProxySettingsActions(
            self._pm,
            is_remote=self.is_remote,
            request_ipc=self._transport.request_ipc,
            translate_event=self._translate_event,
        )
        self._profiles: CliProxyProfileActions = CliProxyProfileActions(
            request_local_headless=self._transport.request_local_headless,
        )

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
        Translates one strict daemon event to CLI output.

        Args:
            code (EventType): The strict daemon event identifier.
            params (Optional[Dict[str, JsonValue]]): The event parameters.

        Returns:
            str: The translated CLI string.
        """
        text, _ = Translator.get(code, params)

        if params and 'alias' in params and '{alias}' in text:
            text = text.replace('{alias}', str(params['alias']))
        elif '{alias}' in text:
            text = text.replace('{alias}', 'unknown')

        return text

    def _prefix_remote(self, text: str) -> str:
        """
        Prepends a remote tag to output strings when necessary.

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

    def _request_ipc(self, cmd: IpcCommand, wait_for_response: bool = True) -> str:
        """
        Routes one IPC command through the transport helper.

        Args:
            cmd (IpcCommand): The outbound command DTO.
            wait_for_response (bool): Whether to await one response.

        Returns:
            str: The formatted CLI response.
        """
        return self._transport.request_ipc(cmd, wait_for_response)

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
        Sets one global setting.

        Args:
            key (str): The setting key.
            value (str): The new value.

        Returns:
            str: Status message.
        """
        return self._settings.handle_settings_set(key, value)

    def handle_settings_get(self, key: str) -> str:
        """
        Retrieves one setting value.

        Args:
            key (str): The setting key.

        Returns:
            str: The formatted response containing the setting value.
        """
        return self._settings.handle_settings_get(key)

    def handle_config_set(self, key: str, value: str) -> str:
        """
        Sets one profile-specific configuration override.

        Args:
            key (str): The config key.
            value (str): The new value.

        Returns:
            str: Status message.
        """
        return self._settings.handle_config_set(key, value)

    def handle_config_get(self, key: str) -> str:
        """
        Retrieves the effective profile-specific configuration value.

        Args:
            key (str): The config key.

        Returns:
            str: The formatted response containing the config value.
        """
        return self._settings.handle_config_get(key)

    def handle_config_sync(self) -> str:
        """
        Wipes profile overrides to restore global defaults for the active profile.

        Args:
            None

        Returns:
            str: Status message.
        """
        return self._settings.handle_config_sync()

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
        Queues an asynchronous offline message.

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

    def list_profiles(self, active_profile: str) -> str:
        """
        Renders the current local profile catalog for the CLI.

        Args:
            active_profile (str): The active profile name.

        Returns:
            str: The formatted profile listing.
        """
        return self._profiles.list_profiles(active_profile)

    def add_profile(
        self,
        name: str,
        *,
        is_remote: bool,
        port: Optional[int],
        security_mode: ProfileSecurityMode,
    ) -> str:
        """
        Creates one local or remote profile via the local headless command path.

        Args:
            name (str): The requested profile name.
            is_remote (bool): Whether the profile is remote.
            port (Optional[int]): Optional static remote port.
            security_mode (ProfileSecurityMode): The requested storage mode.

        Returns:
            str: The formatted operation result.
        """
        return self._profiles.add_profile(
            name,
            is_remote=is_remote,
            port=port,
            security_mode=security_mode,
        )

    def migrate_profile_security(
        self,
        name: str,
        target_mode: ProfileSecurityMode,
        *,
        current_password: Optional[str] = None,
        new_password: Optional[str] = None,
    ) -> str:
        """
        Migrates one local profile between encrypted and plaintext storage.

        Args:
            name (str): The target profile name.
            target_mode (ProfileSecurityMode): The requested storage mode.
            current_password (Optional[str]): The current password when decrypting.
            new_password (Optional[str]): The new password when encrypting.

        Returns:
            str: The formatted operation result.
        """
        return self._profiles.migrate_profile_security(
            name,
            target_mode,
            current_password=current_password,
            new_password=new_password,
        )

    def remove_profile(self, name: str, active_profile: Optional[str]) -> str:
        """
        Removes one local profile through the local headless command path.

        Args:
            name (str): The target profile name.
            active_profile (Optional[str]): The currently active profile to protect.

        Returns:
            str: The formatted operation result.
        """
        return self._profiles.remove_profile(name, active_profile)

    def rename_profile(self, old_name: str, new_name: str) -> str:
        """
        Renames one local profile through the local headless command path.

        Args:
            old_name (str): The current profile name.
            new_name (str): The requested new profile name.

        Returns:
            str: The formatted operation result.
        """
        return self._profiles.rename_profile(old_name, new_name)

    def set_default_profile(self, profile_name: str) -> str:
        """
        Sets the default profile through the local headless command path.

        Args:
            profile_name (str): The requested default profile name.

        Returns:
            str: The formatted operation result.
        """
        return self._profiles.set_default_profile(profile_name)
