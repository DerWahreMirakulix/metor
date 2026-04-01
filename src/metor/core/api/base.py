"""Base IPC DTO types and strict JSON factory helpers."""

import json
import dataclasses
from dataclasses import dataclass, asdict
from enum import Enum
from typing import (
    Dict,
    Mapping,
    Optional,
    Type,
    Set,
    Union,
    List,
    Tuple,
    get_type_hints,
    get_origin,
    get_args,
    TypeVar,
)

# Local Package Imports
from metor.core.api.codes import CommandType, EventType


# Types
JsonValue = Union[
    str, int, float, bool, None, Dict[str, 'JsonValue'], List['JsonValue']
]
T = TypeVar('T')


def _coerce_and_validate(
    cls: Type[T], kwargs: Dict[str, JsonValue]
) -> Dict[str, object]:
    """
    Performs runtime type checking and coercion for incoming JSON dictionaries
    against the static type hints of a target dataclass.

    Args:
        cls (Type[T]): The target dataclass.
        kwargs (Dict[str, JsonValue]): The unvalidated payload dictionary.

    Raises:
        TypeError: If a value violates the strict type hints.
        ValueError: If a non-optional value is None.

    Returns:
        Dict[str, object]: The validated and coerced dictionary ready for instantiation.
    """
    hints: Dict[str, object] = get_type_hints(cls)
    coerced: Dict[str, object] = {}

    for key, value in kwargs.items():
        if key not in hints:
            continue

        expected_type: object = hints[key]
        origin: object = get_origin(expected_type)
        args: Tuple[object, ...] = get_args(expected_type) or ()

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
                    elif isinstance(arg, type) and isinstance(value, arg):
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
                elif isinstance(expected_type, type) and not isinstance(
                    value, expected_type
                ):
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
        data: Dict[str, JsonValue] = {
            k: v for k, v in asdict(self).items() if v is not None
        }
        return json.dumps(data)


@dataclass
class IpcCommand(IpcMessage):
    """Base class for all commands sent to the daemon."""

    command_type: CommandType = dataclasses.field(init=False)

    @classmethod
    def from_dict(cls, data: Dict[str, JsonValue]) -> 'IpcCommand':
        """
        Factory method to instantiate the correct strict subclass based on the command type.

        Args:
            data (Dict[str, JsonValue]): The deserialized JSON payload from the IPC socket.

        Raises:
            TypeError: If type validation fails.

        Returns:
            IpcCommand: The instantiated strictly-typed command.
        """
        from metor.core.api.registry import CMD_MAP

        command_type_val: str = str(data.get('command_type', ''))
        command_type: CommandType = CommandType(command_type_val)
        target_cls: Type['IpcCommand'] = CMD_MAP[command_type]

        valid_keys: Set[str] = {f.name for f in dataclasses.fields(target_cls)}
        kwargs: Dict[str, JsonValue] = {
            k: v for k, v in data.items() if k in valid_keys and k != 'command_type'
        }

        coerced_kwargs: Dict[str, object] = _coerce_and_validate(target_cls, kwargs)
        return target_cls(**coerced_kwargs)


@dataclass
class IpcEvent(IpcMessage):
    """Base class for all events emitted by the daemon."""

    event_type: EventType = dataclasses.field(init=False)

    @classmethod
    def from_dict(cls, data: Dict[str, JsonValue]) -> 'IpcEvent':
        """
        Factory method to instantiate the correct strict subclass based on the event type.

        Args:
            data (Dict[str, JsonValue]): The deserialized JSON payload from the IPC socket.

        Raises:
            TypeError: If type validation fails.

        Returns:
            IpcEvent: The instantiated strictly-typed event.
        """
        from metor.core.api.registry import EVENT_MAP

        event_type_val: str = str(data.get('event_type', ''))
        event_type: EventType = EventType(event_type_val)
        target_cls: Type['IpcEvent'] = EVENT_MAP[event_type]

        valid_keys: Set[str] = {f.name for f in dataclasses.fields(target_cls)}
        kwargs: Dict[str, JsonValue] = {
            k: v for k, v in data.items() if k in valid_keys and k != 'event_type'
        }

        coerced_kwargs: Dict[str, object] = _coerce_and_validate(target_cls, kwargs)
        return target_cls(**coerced_kwargs)


def create_event(
    event_type: EventType,
    params: Optional[Mapping[str, JsonValue]] = None,
) -> IpcEvent:
    """
    Builds a strict IPC event instance from an event type and payload.

    Args:
        event_type (EventType): The concrete event identifier.
        params (Optional[Mapping[str, JsonValue]]): The payload to hydrate into the event DTO.

    Returns:
        IpcEvent: The instantiated strict event DTO.
    """
    payload: Dict[str, JsonValue] = {'event_type': event_type.value}
    if params:
        payload.update(dict(params))
    return IpcEvent.from_dict(payload)
