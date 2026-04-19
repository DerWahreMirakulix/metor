"""Local profile orchestration helpers for the CLI proxy facade."""

from typing import Callable, Optional

from metor.core.api import (
    AddProfileCommand,
    MigrateProfileSecurityCommand,
    ProfileEntry,
    ProfilesDataEvent,
    RemoveProfileCommand,
    RenameProfileCommand,
    SetDefaultProfileCommand,
)
from metor.data import ProfileManager, ProfileSecurityMode
from metor.ui import UIPresenter


class CliProxyProfileActions:
    """Owns local profile flows for the CLI proxy."""

    def __init__(self, *, request_local_headless: Callable[..., str]) -> None:
        """
        Initializes the profile helper.

        Args:
            request_local_headless (Callable[..., str]): Host-local headless request callback.

        Returns:
            None
        """
        self._request_local_headless = request_local_headless

    def list_profiles(self, active_profile: str) -> str:
        """
        Renders the current local profile catalog for the CLI.

        Args:
            active_profile (str): The active profile name.

        Returns:
            str: The formatted profile listing.
        """
        summaries = ProfileManager.get_profile_summaries(active_profile)
        profiles_event = ProfilesDataEvent(
            profiles=[
                ProfileEntry(
                    name=summary.name,
                    is_active=summary.is_active,
                    is_remote=summary.is_remote,
                    port=summary.port,
                )
                for summary in summaries
            ]
        )
        return UIPresenter.format_profiles(profiles_event)

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
        return self._request_local_headless(
            AddProfileCommand(
                name=name,
                is_remote=is_remote,
                port=port,
                security_mode=security_mode.value,
            )
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
        return self._request_local_headless(
            MigrateProfileSecurityCommand(
                name=name,
                target_mode=target_mode.value,
                current_password=current_password,
                new_password=new_password,
            )
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
        return self._request_local_headless(
            RemoveProfileCommand(name=name, active_profile=active_profile)
        )

    def rename_profile(self, old_name: str, new_name: str) -> str:
        """
        Renames one local profile through the local headless command path.

        Args:
            old_name (str): The current profile name.
            new_name (str): The requested new profile name.

        Returns:
            str: The formatted operation result.
        """
        return self._request_local_headless(
            RenameProfileCommand(old_name=old_name, new_name=new_name)
        )

    def set_default_profile(self, profile_name: str) -> str:
        """
        Sets the default profile through the local headless command path.

        Args:
            profile_name (str): The requested default profile name.

        Returns:
            str: The formatted operation result.
        """
        return self._request_local_headless(
            SetDefaultProfileCommand(profile_name=profile_name)
        )
