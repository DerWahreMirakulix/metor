"""Shared helpers for strict IPC DTO modules."""

from typing import ClassVar, Dict, List, Mapping, Sequence, Type, TypeVar, cast

# Local Package Imports
from metor.core.api.base import JsonValue


EntryT = TypeVar('EntryT')


def cast_entry_list(
    values: Sequence[object],
    entry_type: Type[EntryT],
) -> List[EntryT]:
    """
    Casts JSON dictionaries in one list to their concrete DTO entry type.

    Args:
        values (Sequence[object]): The raw nested payload values.
        entry_type (Type[EntryT]): The DTO entry class to instantiate.

    Returns:
        List[EntryT]: The typed entry list.
    """
    if values and isinstance(values[0], dict):
        return [entry_type(**cast(Dict[str, JsonValue], value)) for value in values]
    return [cast(EntryT, value) for value in values]


class NestedEntryCastingMixin:
    """Casts configured nested DTO list fields after dataclass initialization."""

    _nested_entry_types: ClassVar[Mapping[str, Type[object]]] = {}

    def __post_init__(self) -> None:
        """
        Casts configured nested list fields to their strict DTO entry types.

        Args:
            None

        Returns:
            None
        """
        for field_name, entry_type in self._nested_entry_types.items():
            raw_values: Sequence[object] = cast(
                Sequence[object], getattr(self, field_name)
            )
            typed_values: List[object] = cast_entry_list(raw_values, entry_type)
            setattr(self, field_name, typed_values)
