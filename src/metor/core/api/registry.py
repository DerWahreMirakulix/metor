"""Registries used by the IPC DTO factory methods."""

from typing import Dict, Type, Callable, TypeVar

# Local Package Imports
from metor.core.api.codes import CommandType, EventType
from metor.core.api.base import IpcCommand, IpcEvent


# Types
C = TypeVar('C', bound=IpcCommand)
E = TypeVar('E', bound=IpcEvent)


# Global Registries
CMD_MAP: Dict[CommandType, Type[IpcCommand]] = {}
EVENT_MAP: Dict[EventType, Type[IpcEvent]] = {}


def register_command(command_type: CommandType) -> Callable[[Type[C]], Type[C]]:
    """
    Registers an IPC command DTO for a concrete command type.

    Args:
        command_type (CommandType): The top-level command routing value.

    Returns:
        Callable[[Type[C]], Type[C]]: The class decorator that stores the DTO.
    """

    def wrapper(cls: Type[C]) -> Type[C]:
        CMD_MAP[command_type] = cls
        return cls

    return wrapper


def register_event(event_type: EventType) -> Callable[[Type[E]], Type[E]]:
    """
    Registers an IPC event DTO for a concrete event type.

    Args:
        event_type (EventType): The top-level event routing value.

    Returns:
        Callable[[Type[E]], Type[E]]: The class decorator that stores the DTO.
    """

    def wrapper(cls: Type[E]) -> Type[E]:
        EVENT_MAP[event_type] = cls
        return cls

    return wrapper
