"""IPC response rendering helpers for the CLI proxy facade."""

import dataclasses
from typing import Callable, Dict, Optional

from metor.core.api import (
    ContactsDataEvent,
    EventType,
    HistoryDataEvent,
    HistoryRawDataEvent,
    InboxCountsEvent,
    IpcEvent,
    JsonValue,
    MessagesDataEvent,
    ProfileOperationResultEvent,
    ProfilesDataEvent,
    UnreadMessagesEvent,
)
from metor.ui import UIPresenter
from metor.ui.cli.profile import format_profile_result_payload


class CliProxyEventRenderer:
    """Renders strict IPC events into CLI-facing output strings."""

    def __init__(
        self,
        *,
        translate_event: Callable[[EventType, Optional[Dict[str, JsonValue]]], str],
        prefix_remote: Callable[[str], str],
    ) -> None:
        """
        Initializes the event renderer.

        Args:
            translate_event (Callable[[EventType, Optional[Dict[str, JsonValue]]], str]): Event translator callback.
            prefix_remote (Callable[[str], str]): Remote-prefix renderer callback.

        Returns:
            None
        """
        self._translate_event = translate_event
        self._prefix_remote = prefix_remote

    def format_ipc_event(
        self,
        event: IpcEvent,
        *,
        prefix_remote: bool = True,
    ) -> str:
        """
        Formats one typed IPC event for CLI output.

        Args:
            event (IpcEvent): The incoming daemon event DTO.
            prefix_remote (bool): Whether to mark the output as remote.

        Returns:
            str: The rendered CLI text.
        """
        if isinstance(event, ProfileOperationResultEvent):
            profile_text = format_profile_result_payload(
                event.success,
                event.operation_type,
                event.params,
            )
            if prefix_remote:
                return self._prefix_remote(profile_text)
            return profile_text

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
            if prefix_remote:
                return self._prefix_remote(text_fmt)
            return text_fmt

        params_raw: Dict[str, object] = dataclasses.asdict(event)
        params: Dict[str, JsonValue] = {
            key: value
            for key, value in params_raw.items()
            if isinstance(value, (str, int, float, bool, type(None), list, dict))
        }
        translated_text: str = self._translate_event(event.event_type, params)
        if prefix_remote:
            return self._prefix_remote(translated_text)
        return translated_text
