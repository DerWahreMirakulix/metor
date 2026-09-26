"""Native bounded-contact paging, selection and search-focus evidence with synthetic metadata."""

from collections.abc import Callable
from dataclasses import replace

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp

from metor.core.api import ContactEntry
from metor.ui.gui.app import MetorApp
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import Action
from metor.ui.gui.widgets.qr import ContactQr
from metor.ui.gui.widgets.sheet import ActionSheet
from metor.ui.gui.widgets.symbol import IconAction
from test_gui_contacts import address


def configure_contact_pages(controller: GuiController) -> None:
    """Supplies 130 explicit synthetic saved rows and no real address-book operation.

    Args:
        controller: Isolated simulator controller.
    Returns:
        None
    """
    controller.state.route = Route('V12')
    controller.state.snapshot.onion = address(200)
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
    assert view.footer.height == 0
    assert abs(view.next.y - view.y) < dp(1)
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
        current.cancel()
        assert current.footer.height == 0
        assert abs(current.next.y - current.y) < dp(1)
        current.more()
        sheet = ActionSheet.current
        assert sheet is not None
        next(
            widget
            for widget in sheet.walk()
            if isinstance(widget, Action) and widget.accessible_name == 'My QR'
        ).dispatch('on_release')
        assert app.controller.state.route.view == 'V15'
        assert ActionSheet.current is None
        Clock.schedule_once(verify_qr, 0.3)

    def verify_qr(_elapsed: float) -> None:
        """Checks the visible own QR after the menu action rerenders the shell.

        Args:
            _elapsed: Native render delay.
        Returns:
            None
        """
        assert app.shell is not None
        assert any(isinstance(widget, ContactQr) for widget in app.shell.walk())
        app.controller.back()
        app.refresh()
        Clock.schedule_once(scan, 0.3)

    def scan(_elapsed: float) -> None:
        """Checks Scan QR opens its explicit camera/manual step on the first action.

        Args:
            _elapsed: Native render delay.
        Returns:
            None
        """
        assert app.shell is not None
        current = app.shell._contacts_panel
        assert current is not None
        current.more()
        sheet = ActionSheet.current
        assert sheet is not None
        next(
            widget
            for widget in sheet.walk()
            if isinstance(widget, Action) and widget.accessible_name == 'Scan QR'
        ).dispatch('on_release')
        assert app.controller.state.route.view == 'V14'
        assert ActionSheet.current is None
        Clock.schedule_once(verify_scan, 0.3)

    def verify_scan(_elapsed: float) -> None:
        """Checks the scanner fallback is visible, then restores contact paging.

        Args:
            _elapsed: Native render delay.
        Returns:
            None
        """
        assert app.shell is not None
        assert any(
            getattr(widget, 'text', '') == 'Camera unavailable'
            for widget in app.shell.walk()
        )
        app.controller.back()
        app.refresh()
        Clock.schedule_once(add_contact, 0.3)

    def add_contact(_elapsed: float) -> None:
        """Checks Add contact opens its editable form on the first action.

        Args:
            _elapsed: Native render delay.
        Returns:
            None
        """
        assert app.shell is not None
        current = app.shell._contacts_panel
        assert current is not None
        current.more()
        sheet = ActionSheet.current
        assert sheet is not None
        next(
            widget
            for widget in sheet.walk()
            if isinstance(widget, Action) and widget.accessible_name == 'Add contact'
        ).dispatch('on_release')
        assert app.controller.state.route.view == 'V13'
        assert ActionSheet.current is None
        Clock.schedule_once(verify_add, 0.3)

    def verify_add(_elapsed: float) -> None:
        """Checks the editable contact fields render, then returns to paging.

        Args:
            _elapsed: Native render delay.
        Returns:
            None
        """
        assert app.shell is not None
        assert any(
            getattr(widget, 'text', '') == 'Contact address or QR data'
            for widget in app.shell.walk()
        )
        app.controller.back()
        app.refresh()
        Clock.schedule_once(restore, 0.3)

    def restore(_elapsed: float) -> None:
        """Restores the selected final page for the normal native capture.

        Args:
            _elapsed: Native render delay.
        Returns:
            None
        """
        assert app.shell is not None
        current = app.shell._contacts_panel
        assert current is not None
        book = app.controller.contacts.book
        book.selecting = True
        book.toggle(address(0))
        book.toggle(address(129))
        current.update()
        assert book.selected == {address(0), address(129)}
        assert not any(
            isinstance(widget, IconAction)
            for widget in current.search.walk(restrict=True)
        )
        assert app.input_dock is not None
        original_configuration = app.configuration
        app.configuration = replace(original_configuration, touch=True)
        current.search.focus = True
        assert app.input_dock.keyboard is not None
        app.input_dock.hide()
        current.search.focus = False
        current.search.focus = True
        assert app.input_dock.keyboard is not None
        app.input_dock.hide()
        current.search.focus = False
        app.configuration = original_configuration
        complete()

    Clock.schedule_once(verify, 0.3)
