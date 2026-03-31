"""
Module providing the central routing registries for IPC deserialization factories.
Utilizes a dynamic Decorator-Pattern to register commands and events, upholding the Open-Closed Principle (OCP).
"""

from typing import Dict, Type, Callable, TypeVar

# Local Package Imports
from metor.core.api.codes import Action, EventType
from metor.core.api.base import IpcCommand, IpcEvent


# Types
C = TypeVar('C', bound=IpcCommand)
E = TypeVar('E', bound=IpcEvent)


# Global Registries
CMD_MAP: Dict[Action, Type[IpcCommand]] = {}
EVENT_MAP: Dict[EventType, Type[IpcEvent]] = {}


def register_command(action: Action) -> Callable[[Type[C]], Type[C]]:
    """
    Decorator to dynamically register an IpcCommand DTO to a specific Action enum.

    Args:
        action (Action): The strict IPC action code.

    Returns:
        Callable[[Type[C]], Type[C]]: The decorated class.
    """

    def wrapper(cls: Type[C]) -> Type[C]:
        CMD_MAP[action] = cls
        return cls

    return wrapper


def register_event(event_type: EventType) -> Callable[[Type[E]], Type[E]]:
    """
    Decorator to dynamically register an IpcEvent DTO to a specific EventType enum.

    Args:
        event_type (EventType): The strict IPC event type code.

    Returns:
        Callable[[Type[E]], Type[E]]: The decorated class.
    """

    def wrapper(cls: Type[E]) -> Type[E]:
        EVENT_MAP[event_type] = cls
        return cls

    return wrapper
