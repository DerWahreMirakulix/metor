"""Base IPC DTO types and strict JSON factory helpers."""

import contextlib
import contextvars
import dataclasses
import json
import secrets
from collections.abc import Mapping as MappingABC
from collections.abc import Sequence as SequenceABC
from dataclasses import asdict, dataclass
from enum import Enum
from types import UnionType
from typing import (
    Callable,
    Dict,
    ForwardRef,
    Iterator,
    List,
    Mapping,
    Optional,
    Set,
    Type,
    TypeVar,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

# Local Package Imports
from metor.core.api.codes import CommandType, EventType


# Types
JsonValue = Union[
    str, int, float, bool, None, Dict[str, 'JsonValue'], List['JsonValue']
]
T = TypeVar('T')
_CURRENT_REQUEST_ID: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    'metor_ipc_request_id',
    default=None,
)


def _reject_unknown_fields(
    cls: Type[T],
    data: Dict[str, JsonValue],
    valid_keys: Set[str],
    route_key: str,
) -> None:
    """
    Rejects unknown payload fields to keep the IPC schema strict.

    Args:
        cls (Type[T]): The target DTO type.
        data (Dict[str, JsonValue]): The incoming payload.
        valid_keys (Set[str]): Allowed dataclass field names.
        route_key (str): The routing field name to ignore.

    Raises:
        TypeError: If unknown fields are present.

    Returns:
        None
    """
    unknown_fields: List[str] = sorted(
        key for key in data.keys() if key != route_key and key not in valid_keys
    )
    if unknown_fields:
        joined_fields: str = ', '.join(unknown_fields)
        raise TypeError(f'Unknown fields for {cls.__name__}: {joined_fields}.')


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
    return {
        key: _validate_value(hints[key], value, key)
        for key, value in kwargs.items()
        if key in hints
    }


def _validate_value(expected_type: object, value: object, path: str) -> object:
    """Recursively validates and hydrates one JSON-shaped DTO field value.

    Args:
        expected_type (object): Resolved annotation describing the accepted value.
        value (object): Decoded JSON value to validate.
        path (str): Human-readable location used in validation errors.

    Raises:
        TypeError: If the value does not conform to the declared IPC type.

    Returns:
        object: The validated primitive, container, enum, or nested dataclass.
    """
    if isinstance(expected_type, ForwardRef):
        if expected_type.__forward_arg__ != 'JsonValue':
            raise TypeError(f"Field '{path}' has an unsupported forward reference.")
        return _validate_value(JsonValue, value, path)

    origin: object = get_origin(expected_type)
    args: tuple[object, ...] = get_args(expected_type)

    if origin in (Union, UnionType):
        for union_type in args:
            try:
                return _validate_value(union_type, value, path)
            except (TypeError, ValueError):
                continue
        raise TypeError(
            f"Field '{path}' expected {expected_type}, got {type(value).__name__}."
        )

    if expected_type is type(None):
        if value is None:
            return None
        raise TypeError(f"Field '{path}' expected null, got {type(value).__name__}.")

    if origin is list:
        if not isinstance(value, list) or len(args) != 1:
            raise TypeError(f"Field '{path}' expected a typed JSON array.")
        return [
            _validate_value(args[0], item, f'{path}[{index}]')
            for index, item in enumerate(value)
        ]

    if origin is SequenceABC:
        if not isinstance(value, list) or len(args) != 1:
            raise TypeError(f"Field '{path}' expected a typed JSON array.")
        return [
            _validate_value(args[0], item, f'{path}[{index}]')
            for index, item in enumerate(value)
        ]

    if origin in (dict, MappingABC):
        if not isinstance(value, dict) or len(args) != 2:
            raise TypeError(f"Field '{path}' expected a typed JSON object.")
        return {
            _validate_value(args[0], key, f'{path}.<key>'): _validate_value(
                args[1], item, f'{path}[{key!r}]'
            )
            for key, item in value.items()
        }

    if isinstance(expected_type, type) and issubclass(expected_type, Enum):
        try:
            return expected_type(value)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                f"Field '{path}' expected {expected_type.__name__}."
            ) from exc

    if isinstance(expected_type, type) and dataclasses.is_dataclass(expected_type):
        return _validate_dataclass(expected_type, value, path)

    if expected_type is int:
        if type(value) is int:
            return value
    elif expected_type is bool:
        if type(value) is bool:
            return value
    elif expected_type is float:
        if type(value) is float:
            return value
    elif expected_type is str:
        if type(value) is str:
            return value
    else:
        raise TypeError(f"Field '{path}' uses unsupported type {expected_type!r}.")

    raise TypeError(
        f"Field '{path}' expected {expected_type}, got {type(value).__name__}."
    )


def _validate_dataclass(expected_type: Type[T], value: object, path: str) -> T:
    """Validates and hydrates one nested dataclass payload.

    Args:
        expected_type (Type[T]): Concrete nested DTO class.
        value (object): JSON object or an already hydrated instance.
        path (str): Human-readable location used in validation errors.

    Raises:
        TypeError: If the nested value or discriminator violates the DTO schema.

    Returns:
        T: The validated nested DTO instance.
    """
    if isinstance(value, expected_type):
        return value
    if not isinstance(value, dict):
        raise TypeError(f"Field '{path}' expected {expected_type.__name__}.")

    fields: tuple[dataclasses.Field[object], ...] = dataclasses.fields(
        expected_type  # type: ignore[arg-type]
    )
    valid_keys: Set[str] = {field.name for field in fields}
    _reject_unknown_fields(
        expected_type,
        cast(Dict[str, JsonValue], value),
        valid_keys,
        '',
    )
    for field in fields:
        if field.init or field.default is dataclasses.MISSING:
            continue
        expected_discriminator: object = field.default
        if isinstance(expected_discriminator, Enum):
            expected_discriminator = expected_discriminator.value
        if value.get(field.name) != expected_discriminator:
            raise TypeError(
                f"Field '{path}.{field.name}' has an invalid discriminator."
            )

    nested_kwargs: Dict[str, JsonValue] = {
        key: cast(JsonValue, item)
        for key, item in value.items()
        if key in valid_keys
        and next(field for field in fields if field.name == key).init
    }
    try:
        return _instantiate_validated_message(
            expected_type,
            _coerce_and_validate(expected_type, nested_kwargs),
        )
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"Field '{path}' is not a valid {expected_type.__name__}."
        ) from exc


def _instantiate_validated_message(cls: Type[T], kwargs: Dict[str, object]) -> T:
    """
    Instantiates one validated DTO while keeping the strict runtime validation path.

    Args:
        cls (Type[T]): The target DTO type.
        kwargs (Dict[str, object]): The validated constructor payload.

    Returns:
        T: The instantiated DTO.
    """
    constructor: Callable[..., T] = cast(Callable[..., T], cls)
    return constructor(**kwargs)


@dataclass
class IpcMessage:
    """
    Base class providing JSON serialization for all IPC messages.

    Attributes:
        None
    """

    request_id: Optional[str] = dataclasses.field(default=None, kw_only=True)

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
        _reject_unknown_fields(target_cls, data, valid_keys, 'command_type')
        kwargs: Dict[str, JsonValue] = {
            k: v for k, v in data.items() if k in valid_keys and k != 'command_type'
        }

        coerced_kwargs: Dict[str, object] = _coerce_and_validate(target_cls, kwargs)
        return _instantiate_validated_message(target_cls, coerced_kwargs)


@dataclass
class IpcEvent(IpcMessage):
    """Base class for all events emitted by the daemon."""

    revision: Optional[int] = dataclasses.field(default=None, kw_only=True)
    epoch: Optional[str] = dataclasses.field(default=None, kw_only=True)
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
        _reject_unknown_fields(target_cls, data, valid_keys, 'event_type')
        kwargs: Dict[str, JsonValue] = {
            k: v for k, v in data.items() if k in valid_keys and k != 'event_type'
        }

        coerced_kwargs: Dict[str, object] = _coerce_and_validate(target_cls, kwargs)
        return _instantiate_validated_message(target_cls, coerced_kwargs)


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
    return stamp_request_id(IpcEvent.from_dict(payload))


def create_request_id() -> str:
    """
    Creates one cryptographically strong IPC request correlation identifier.

    Args:
        None

    Returns:
        str: The newly generated request identifier.
    """
    return secrets.token_hex(16)


def ensure_request_id(message: IpcMessage) -> str:
    """
    Ensures one IPC DTO carries a stable request identifier.

    Args:
        message (IpcMessage): The DTO to annotate.

    Returns:
        str: The existing or newly assigned request identifier.
    """
    if message.request_id is None:
        message.request_id = create_request_id()
    return message.request_id


def get_current_request_id() -> Optional[str]:
    """
    Returns the active request correlation identifier for the current execution context.

    Args:
        None

    Returns:
        Optional[str]: The current request identifier, if one is active.
    """
    return _CURRENT_REQUEST_ID.get()


@contextlib.contextmanager
def request_context(request_id: Optional[str]) -> Iterator[None]:
    """
    Installs one request correlation identifier for the current execution context.

    Args:
        request_id (Optional[str]): The request identifier to expose during the context.

    Returns:
        None
    """
    token = _CURRENT_REQUEST_ID.set(request_id)
    try:
        yield
    finally:
        _CURRENT_REQUEST_ID.reset(token)


def stamp_request_id(
    message: T,
    request_id: Optional[str] = None,
) -> T:
    """
    Applies one request identifier to an IPC DTO when it does not already carry one.

    Args:
        message (T): The DTO to annotate.
        request_id (Optional[str]): Optional explicit request identifier override.

    Returns:
        T: The same DTO instance for fluent call sites.
    """
    effective_request_id: Optional[str] = request_id or get_current_request_id()
    if isinstance(message, IpcMessage) and message.request_id is None:
        message.request_id = effective_request_id
    return message
