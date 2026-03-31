"""
Module defining the abstract base classes and factory logic for IPC communication.
Implements runtime type validation to protect daemon deserialization from malformed payloads.
"""

import json
import dataclasses
from dataclasses import dataclass, asdict
from enum import Enum
from typing import (
    Dict,
    Tuple,
    Type,
    Set,
    Union,
    List,
    Any,
    get_type_hints,
    get_origin,
    get_args,
)

# Local Package Imports
from metor.core.api.codes import Action, EventType


JsonValue = Union[
    str, int, float, bool, None, Dict[str, 'JsonValue'], List['JsonValue']
]


def _coerce_and_validate(cls: Type[Any], kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Performs runtime type checking and coercion for incoming JSON dictionaries
    against the static type hints of a target dataclass.

    Args:
        cls (Type[Any]): The target dataclass.
        kwargs (Dict[str, Any]): The unvalidated payload dictionary.

    Raises:
        TypeError: If a value violates the strict type hints.
        ValueError: If a non-optional value is None.

    Returns:
        Dict[str, Any]: The validated and coerced dictionary ready for instantiation.
    """
    hints: Dict[str, Any] = get_type_hints(cls)
    coerced: Dict[str, Any] = {}

    for key, value in kwargs.items():
        if key not in hints:
            continue

        expected_type: Any = hints[key]
        origin: Any = get_origin(expected_type)
        args: Tuple[Any, ...] = get_args(expected_type)

        if origin is Union:
            is_optional: bool = type(None) in args
            if value is None:
                if not is_optional:
                    raise ValueError(f"Field '{key}' cannot be null.")
                coerced[key] = None
                continue

            valid: bool = False
            for arg in args:
                if arg is type(None):
                    continue
                try:
                    if isinstance(arg, type) and issubclass(arg, Enum):
                        coerced[key] = arg(value)
                        valid = True
                        break
                    elif isinstance(value, arg):
                        coerced[key] = value
                        valid = True
                        break
                except (ValueError, TypeError):
                    pass

            if not valid:
                raise TypeError(
                    f"Field '{key}' expected {expected_type}, got {type(value)}."
                )

        else:
            if value is None:
                raise ValueError(f"Field '{key}' cannot be null.")
            try:
                if isinstance(expected_type, type) and issubclass(expected_type, Enum):
                    coerced[key] = expected_type(value)
                elif origin in (list, dict):
                    if not isinstance(value, (list, dict)):
                        raise TypeError()
                    coerced[key] = value
                elif not isinstance(value, expected_type):
                    raise TypeError()
                else:
                    coerced[key] = value
            except (ValueError, TypeError) as e:
                raise TypeError(
                    f"Field '{key}' expected {expected_type}, got {type(value)}."
                ) from e

    return coerced


@dataclass
class IpcMessage:
    """
    Base class providing JSON serialization for all IPC messages.

    Attributes:
        None
    """

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
    """
    Base class for all commands sent to the Daemon.

    Attributes:
        None
    """

    @classmethod
    def from_dict(cls, data: Dict[str, JsonValue]) -> 'IpcCommand':
        """
        Factory method to instantiate the correct strict subclass based on the Action enum.
        Applies runtime type validation to prevent malformed injections.

        Args:
            data (Dict[str, JsonValue]): The deserialized JSON payload from the IPC socket.

        Raises:
            TypeError: If type validation fails.

        Returns:
            IpcCommand: The instantiated strictly-typed command.
        """
        from metor.core.api.registry import CMD_MAP

        action_val: str = str(data['action'])
        action: Action = Action(action_val)
        target_cls: Type['IpcCommand'] = CMD_MAP[action]

        valid_keys: Set[str] = {f.name for f in dataclasses.fields(target_cls)}
        kwargs: Dict[str, Any] = {
            k: v for k, v in data.items() if k in valid_keys and k != 'action'
        }

        coerced_kwargs: Dict[str, Any] = _coerce_and_validate(target_cls, kwargs)
        return target_cls(**coerced_kwargs)


@dataclass
class IpcEvent(IpcMessage):
    """
    Base class for all events emitted by the Daemon.

    Attributes:
        None
    """

    @classmethod
    def from_dict(cls, data: Dict[str, JsonValue]) -> 'IpcEvent':
        """
        Factory method to instantiate the correct strict subclass based on the EventType enum.
        Applies runtime type validation to prevent malformed injections.

        Args:
            data (Dict[str, JsonValue]): The deserialized JSON payload from the IPC socket.

        Raises:
            TypeError: If type validation fails.

        Returns:
            IpcEvent: The instantiated strictly-typed event.
        """
        from metor.core.api.registry import EVENT_MAP

        type_val: str = str(data['type'])
        event_type: EventType = EventType(type_val)
        target_cls: Type['IpcEvent'] = EVENT_MAP[event_type]

        valid_keys: Set[str] = {f.name for f in dataclasses.fields(target_cls)}
        kwargs: Dict[str, Any] = {
            k: v for k, v in data.items() if k in valid_keys and k != 'type'
        }

        coerced_kwargs: Dict[str, Any] = _coerce_and_validate(target_cls, kwargs)
        return target_cls(**coerced_kwargs)
