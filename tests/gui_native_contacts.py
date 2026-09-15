"""Native bounded-contact paging, selection and search-focus evidence with synthetic metadata."""

from collections.abc import Callable
from dataclasses import replace

from kivy.clock import Clock
from kivy.core.window import Window

from metor.core.api import ContactEntry
from metor.ui.gui.app import MetorApp
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from test_gui_contacts import address


def configure_contact_pages(controller: GuiController) -> None:
    """Supplies 130 explicit synthetic saved rows and no real address-book operation.

    Args:
        controller: Isolated simulator controller.
    Returns:
        None
    """
    controller.state.route = Route('V12')
    controller.state.snapshot.contacts = [
        ContactEntry('Person ' + str(index).zfill(3), address(index))
        for index in range(130)
    ]


def exercise_contact_pages(app: MetorApp, complete: Callable[[], None]) -> None:
    """Checks 64/64/2 native row pages, immutable selection and stable search on new snapshots.

    Args:
        app: Running isolated native simulator.
        complete: Called after selected final-page geometry settles.
    Returns:
        None
    """
    view = app.shell._contacts_panel
    assert view is not None
    assert len(view._rows) == 64
    original_search = view.search
    first = view._rows[address(0)]
    app.controller.contacts.book.selecting = True
    view.update()
    first = view._rows[address(0)]
    first.focus = True
    Window.dispatch('on_key_down', 274, 81, '', [])
    Window.dispatch('on_key_up', 274, 81)
    assert view._rows[address(1)].focus
    assert not app.controller.contacts.book.selected
    assert app.controller.state.route.view == 'V12'
    Window.dispatch('on_key_down', 273, 82, '', [])
    Window.dispatch('on_key_up', 273, 82)
    assert first.focus
    Window.dispatch('on_key_down', 13, 40, '\r', [])
    Window.dispatch('on_key_up', 13, 40)
    assert app.controller.contacts.book.selected == {address(0)}
    view.page(1)
    assert len(view._rows) == 64 and view.page_label.text == '2 / 3'
    view.page(1)
    assert len(view._rows) == 2 and view.page_label.text == '3 / 3'
    view.select(address(129))
    assert app.controller.contacts.book.selected == {address(0), address(129)}
    view.search.text = 'Person'
    view.search.focus = True
    state = app.controller.state
    state.snapshot = replace(
        state.snapshot, revision=(state.snapshot.revision or 0) + 1
    )
    app.refresh()

    def verify(_elapsed: float) -> None:
        """Verifies native ownership after the normal application refresh loop.

        Args:
            _elapsed: Native frame interval.
        Returns:
            None
        """
        current = app.shell._contacts_panel
        assert current is view and current.search is original_search
        assert current.search.focus and current.search.text == 'Person'
        assert app.controller.contacts.book.selected == {address(0), address(129)}
        current.search.focus = False
        current.page(1)
        current.page(1)
        assert len(current._rows) == 2
        assert current.footer.height > 0
        assert app.controller.client is None
        complete()

    Clock.schedule_once(verify, 0.3)
