"""History command DTOs for projected and raw history retrieval."""

from dataclasses import dataclass, field
from typing import Optional

from metor.shared import Constants

from metor.core.api.base import IpcCommand
from metor.core.api.codes import CommandType
from metor.core.api.registry import register_command


def _validate_page(
    page_size: Optional[int], before_id: Optional[int], limit: Optional[int]
) -> None:
    """Validates opt-in finite metadata pages without changing legacy limit queries.

    Args:
        page_size: Maximum raw rows scanned for one page.
        before_id: Exclusive, profile-local ledger anchor.
        limit: Legacy result limit, unavailable together with paging.
    Returns:
        None
    """
    if page_size is None:
        if before_id is not None:
            raise ValueError('History anchor requires paging')
        return
    if (
        type(page_size) is not int
        or not 1 <= page_size <= Constants.HISTORY_PAGE_MAX_ITEMS
    ):
        raise ValueError('Invalid history page size')
    if limit is not None:
        raise ValueError('History paging cannot use a legacy limit')
    if before_id is not None and (
        type(before_id) is not int or not 1 <= before_id <= Constants.HISTORY_ANCHOR_MAX
    ):
        raise ValueError('Invalid history anchor')


@register_command(CommandType.GET_HISTORY)
@dataclass
class GetHistoryCommand(IpcCommand):
    """Requests projected user-facing history summary."""

    target: Optional[str] = None
    limit: Optional[int] = None
    page_size: Optional[int] = None
    before_id: Optional[int] = None
    command_type: CommandType = field(default=CommandType.GET_HISTORY, init=False)

    def __post_init__(self) -> None:
        """Checks finite opt-in history paging.

        Args:
            None
        Returns:
            None
        """
        _validate_page(self.page_size, self.before_id, self.limit)


@register_command(CommandType.GET_RAW_HISTORY)
@dataclass
class GetRawHistoryCommand(IpcCommand):
    """Requests the raw transport history ledger."""

    target: Optional[str] = None
    limit: Optional[int] = None
    page_size: Optional[int] = None
    before_id: Optional[int] = None
    command_type: CommandType = field(
        default=CommandType.GET_RAW_HISTORY,
        init=False,
    )

    def __post_init__(self) -> None:
        """Checks finite opt-in technical history paging.

        Args:
            None
        Returns:
            None
        """
        _validate_page(self.page_size, self.before_id, self.limit)


@register_command(CommandType.CLEAR_HISTORY)
@dataclass
class ClearHistoryCommand(IpcCommand):
    """Clears persisted history rows."""

    target: Optional[str] = None
    command_type: CommandType = field(default=CommandType.CLEAR_HISTORY, init=False)
