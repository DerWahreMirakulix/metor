"""
Module defining the abstract base classes and factory logic for IPC communication.
Utilizes deferred imports for the mapping registry to prevent circular dependencies.
"""

import json
import dataclasses
from dataclasses import dataclass, asdict
from typing import Dict, Any, Type, Set

# Local Package Imports
from metor.core.api.codes import Action, EventType


@dataclass
class IpcMessage:
    """Base class providing JSON serialization for all IPC messages."""

    def to_json(self) -> str:
        """
        Serializes the current DTO into a JSON string, excluding None values.

        Args:
            None

        Returns:
            str: The serialized JSON string.
        """
        data: Dict[str, Any] = {k: v for k, v in asdict(self).items() if v is not None}
        return json.dumps(data)


@dataclass
class IpcCommand(IpcMessage):
    """Base class for all commands sent to the Daemon."""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IpcCommand':
        """
        Factory method to instantiate the correct strict subclass based on the Action enum.

        Args:
            data (Dict[str, Any]): The deserialized JSON payload from the IPC socket.

        Returns:
            IpcCommand: The instantiated strictly-typed command.
        """
        # Deferred import to avoid circular dependencies with the registry
        from metor.core.api.registry import CMD_MAP

        action: Action = Action(data['action'])
        target_cls: Type['IpcCommand'] = CMD_MAP[action]
        valid_keys: Set[str] = {f.name for f in dataclasses.fields(target_cls)}
        kwargs: Dict[str, Any] = {
            k: v for k, v in data.items() if k in valid_keys and k != 'action'
        }
        return target_cls(**kwargs)


@dataclass
class IpcEvent(IpcMessage):
    """Base class for all events emitted by the Daemon."""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IpcEvent':
        """
        Factory method to instantiate the correct strict subclass based on the EventType enum.

        Args:
            data (Dict[str, Any]): The deserialized JSON payload from the IPC socket.

        Returns:
            IpcEvent: The instantiated strictly-typed event.
        """
        # Deferred import to avoid circular dependencies with the registry
        from metor.core.api.registry import EVENT_MAP

        event_type: EventType = EventType(data['type'])
        target_cls: Type['IpcEvent'] = EVENT_MAP[event_type]
        valid_keys: Set[str] = {f.name for f in dataclasses.fields(target_cls)}
        kwargs: Dict[str, Any] = {
            k: v for k, v in data.items() if k in valid_keys and k != 'type'
        }
        return target_cls(**kwargs)
