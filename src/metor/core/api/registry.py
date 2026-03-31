"""
Module providing the central routing registries for IPC deserialization factories.
Utilizes a dynamic Decorator-Pattern to register commands and events, upholding the Open-Closed Principle (OCP).
"""

from typing import Dict, Type, Any, Callable

# Local Package Imports
from metor.core.api.codes import Action, EventType


CMD_MAP: Dict[Action, Type[Any]] = {}
EVENT_MAP: Dict[EventType, Type[Any]] = {}


def register_command(action: Action) -> Callable[[Type[Any]], Type[Any]]:
    """
    Decorator to dynamically register an IpcCommand DTO to a specific Action enum.

    Args:
        action (Action): The strict IPC action code.

    Returns:
        Callable[[Type[Any]], Type[Any]]: The decorated class.
    """

    def wrapper(cls: Type[Any]) -> Type[Any]:
        CMD_MAP[action] = cls
        return cls

    return wrapper


def register_event(event_type: EventType) -> Callable[[Type[Any]], Type[Any]]:
    """
    Decorator to dynamically register an IpcEvent DTO to a specific EventType enum.

    Args:
        event_type (EventType): The strict IPC event type code.

    Returns:
        Callable[[Type[Any]], Type[Any]]: The decorated class.
    """

    def wrapper(cls: Type[Any]) -> Type[Any]:
        EVENT_MAP[event_type] = cls
        return cls

    return wrapper
