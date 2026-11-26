"""Correlated continuation of one frozen explicit address-book listing."""

from metor.core.api import ContactsDataEvent, GetContactsListCommand, ensure_request_id


class ContactListRead:
    """Advance only through pages of the exact requested contact inventory."""

    def __init__(self, command: GetContactsListCommand) -> None:
        """Bind the first page to this frontend request."""
        self.command = command
        self.profile: str | None = None
        ensure_request_id(command)

    def advance(self, page: ContactsDataEvent) -> GetContactsListCommand | None:
        """Validate progress before rendering, and return the next correlated request."""
        if (
            page.checked_onions is not None
            or page.page_offset != self.command.offset
            or (self.profile is not None and page.profile != self.profile)
            or (
                self.command.snapshot_id is not None
                and page.snapshot_id != self.command.snapshot_id
            )
        ):
            raise ValueError('Contact inventory changed')
        self.profile = page.profile
        if page.next_offset is None:
            return None
        row_count = len(page.saved) + len(page.discovered)
        if not row_count or page.next_offset != page.page_offset + row_count:
            raise ValueError('Invalid contact continuation')
        self.command = GetContactsListCommand(
            chat_mode=self.command.chat_mode,
            snapshot_id=page.snapshot_id,
            offset=page.next_offset,
        )
        ensure_request_id(self.command)
        return self.command
