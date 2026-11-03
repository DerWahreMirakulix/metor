"""Native root refresh proof using actual screen coordinates and canonical peer focus."""

from collections.abc import Callable
from dataclasses import replace

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.scrollview import ScrollView

from metor.core.api import Delivery, DropConversationSummaryEntry
from metor.ui.gui.app import MetorApp
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import Action, Label


def exercise_root_navigation(app: MetorApp, complete: Callable[[], None]) -> None:
    """Uses native sidebar and Back controls across compact and wide root routes.

    Args:
        app: Running isolated native simulator.
        complete: Continuation after presentation-only navigation returns to root.
    Returns:
        None
    """
    assert app.shell is not None
    shell, state = app.shell, app.controller.state

    def assert_overview(view: str) -> None:
        """Checks the actual compact list or wide neutral detail after Back.

        Args:
            view: Expected DROP or LIVE root route.
        Returns:
            None
        """
        assert state.route.view == view
        assert shell._root_panel is not None
        assert shell._root_panel.get_root_window() is not None
        if shell.width >= dp(960):
            assert any(
                isinstance(widget, Label) and widget.text == 'Choose a conversation'
                for widget in shell.walk()
            )
        else:
            assert shell._contacts_panel is None and shell._detail is None

    assert_overview('V06')
    root = shell._root_panel
    contacts, settings, bell = (
        root.header_actions[view] for view in ('V12', 'V17', 'V16')
    )
    for target in (contacts, settings, bell):
        assert target.width >= dp(48) and target.height >= dp(48)
    assert contacts.right < settings.x < settings.right < bell.x
    tray = bell.parent
    assert tray is not None
    assert abs((contacts.x - tray.x) - (tray.right - bell.right)) <= dp(1)
    assert abs((tray.top - bell.top) - (bell.y - tray.y)) <= dp(1)
    assert abs(tray.right - root.new.right) <= dp(1)
    root.header_actions['V12'].dispatch('on_release')
    shell.render()
    assert state.route.view == 'V12' and shell._contacts_panel is not None
    if shell.width >= dp(960):
        assert root.header_actions['V12'].surface == 'dropSurface'
        assert root.tabs[Delivery.DROP].surface == 'dropSurface'
        assert root.new.surface == 'drop' and root.new._tone == 'onAccent'
        root.tabs[Delivery.LIVE].dispatch('on_release')
        shell.render()
        assert state.route.view == 'V12' and state.root_delivery is Delivery.LIVE
        assert shell._contacts_panel is not None
        assert shell._root_panel.tabs[Delivery.LIVE].surface == 'liveSurface'
        assert shell._root_panel.new.surface == 'live'
    shell._contacts_panel.back.dispatch('on_release')
    shell.render()
    if shell.width >= dp(960):
        assert_overview('V07')
        shell._root_panel.tabs[Delivery.DROP].dispatch('on_release')
        shell.render()
    assert_overview('V06')

    root = shell._root_panel
    root.new.dispatch('on_release')
    shell.render()
    assert state.route.view == 'V11' and shell._contacts_panel is not None
    shell._contacts_panel.back.dispatch('on_release')
    shell.render()
    assert_overview('V06')

    root = shell._root_panel
    root.tabs[Delivery.LIVE].dispatch('on_release')
    shell.render()
    assert state.route.view == 'V07' and state.root_delivery is Delivery.LIVE
    root = shell._root_panel
    root.new.dispatch('on_release')
    shell.render()
    assert state.route.view == 'V11' and shell._contacts_panel is not None
    assert state.route.delivery is Delivery.LIVE
    shell._contacts_panel.back.dispatch('on_release')
    shell.render()
    assert_overview('V07')

    if shell.width >= dp(960):
        root = shell._root_panel
        root.new.focus = True
        root.new.dispatch('on_release')
        shell.render()
        notifications = root.header_actions['V16']
        notifications.focus = True
        notifications.dispatch('on_release')
        shell.render()
        assert state.route.view == 'V16'
        assert not root.new.focus and root.new.surface == 'live'
        assert notifications.surface == 'dropSurface'
        assert 'current view' in notifications.accessible_name
        app.controller.back()
        shell.render()
        assert_overview('V07')

        root = shell._root_panel
        settings = root.header_actions['V17']
        settings.dispatch('on_release')
        shell.render()
        root = shell._root_panel
        settings = root.header_actions['V17']
        assert state.route.view == 'V17'
        assert settings.surface == 'dropSurface'
        assert 'current view' in settings.accessible_name
        assert not root.header_actions['V16'].focus
        assert root.header_actions['V16'].surface == 'surface'
        assert root.tabs[Delivery.LIVE].surface == 'liveSurface'
        assert root.new.surface == 'live' and root.new._tone == 'onAccent'
        detail = shell._detail
        root.tabs[Delivery.DROP].dispatch('on_release')
        shell.render()
        root = shell._root_panel
        assert state.route.view == 'V17' and state.root_delivery is Delivery.DROP
        assert shell._detail is detail
        assert root.tabs[Delivery.DROP].surface == 'dropSurface'
        assert root.tabs[Delivery.LIVE].surface == 'surface'
        assert root.new.label.text == 'New Drop' and root.new.surface == 'drop'
        root.tabs[Delivery.LIVE].dispatch('on_release')
        shell.render()
        assert state.route.view == 'V17' and shell._detail is detail
        app.controller.back()
        shell.render()
        assert_overview('V07')

        root = shell._root_panel
        root.header_actions['V17'].dispatch('on_release')
        shell.render()
        app.controller.navigate(Route('V20'))
        shell.render()
        app.controller.poll()
        my_contact = next(
            widget
            for widget in shell._detail.walk(restrict=True)
            if isinstance(widget, Action) and widget.accessible_name == 'My contact'
        )
        my_contact.dispatch('on_release')
        assert state.route.view == 'V15'
        assert app.controller.poll()
        shell.render()
        identity_detail = shell._detail
        assert identity_detail is not None
        assert any(
            isinstance(widget, Label) and widget.text == 'My contact'
            for widget in identity_detail.walk(restrict=True)
        )
        shell.render()
        assert shell._detail is identity_detail
        app.controller.back()
        shell.render()
        assert state.route.view == 'V20'
        app.controller.back()
        shell.render()
        assert state.route.view == 'V17'
        root = shell._root_panel
        root.tabs[Delivery.DROP].dispatch('on_release')
        shell.render()
        root = shell._root_panel
        row = next(iter(root.rows.values()))
        row.action.dispatch('on_release')
        shell.render()
        assert state.route == Route('V08', row.entry.peer, Delivery.DROP)
        assert shell._peer_panel is not None
        app.controller.back()
        shell.render()
        assert_overview('V06')

    shell._root_panel.tabs[Delivery.DROP].dispatch('on_release')
    shell.render()
    assert_overview('V06')
    assert app.controller.client is None
    complete()


def exercise_root_refresh(app: MetorApp, complete: Callable[[], None]) -> None:
    """Changes root metadata while an older row owns focus and a visible pixel anchor.

    Args:
        app: Native simulator with 130 synthetic conversation summaries.
        complete: Continuation after rebuilt native bounds have settled.
    Returns:
        None
    """

    def after_layout(callback: Callable[[float], None], frames: int = 5) -> None:
        """Waits for nested native layout frames, independent of software GL frame time.

        Args:
            callback: Assertion or input to execute after layout.
            frames: Remaining native frames, including deferred continuity restoration.
        Returns:
            None
        """
        if frames:
            Clock.schedule_once(lambda elapsed: after_layout(callback, frames - 1), 0)
        else:
            callback(0)

    assert app.shell is not None
    controller = app.controller
    controller.state.root_pages[Delivery.DROP] = 0
    snapshot = controller.state.snapshot
    assert snapshot is not None
    aliases = ('W' * 320, ('North Station Field Engineering ' * 11)[:320].rstrip())
    examples = [
        replace(summary, alias=alias)
        for summary, alias in zip(snapshot.conversations[:2], aliases, strict=True)
    ]
    controller.state.snapshot = replace(
        snapshot, conversations=examples + snapshot.conversations[2:]
    )
    app.shell.render()

    def check_previews(_elapsed: float) -> None:
        """Long natural and unbroken names stay readable without displacing the list."""
        root = app.shell._root_panel
        ordinary = root.rows[snapshot.conversations[2].onion]
        for sample in examples:
            row = root.rows[sample.onion]
            assert row.name.text.endswith('…') and sample.alias.startswith(
                row.name.text[:-1]
            )
            assert row.name.height <= 3 * ordinary.name.height + 1
            assert row.action.accessible_name.startswith(sample.alias)
            assert row.action.label.text == ''
        root.rows[examples[0].onion].action.dispatch('on_release')
        app.shell.render()
        after_layout(check_detail)

    def check_detail(_elapsed: float) -> None:
        """Opening the bounded list preview shows the original identity and its actions."""
        panel = app.shell._peer_panel
        assert panel is not None and panel.name.text == aliases[0]
        viewport = panel.header_viewport
        name_viewport = panel.header.name_viewport
        assert name_viewport.do_scroll_y and name_viewport.scroll_y == 1
        if app.shell.width < dp(960):
            assert viewport.height <= 0.4 * panel.height + 1
            assert panel.timeline.height >= max(viewport.height, 0.4 * panel.height)
        bottom = viewport.to_window(viewport.x, viewport.y)[1]
        for action in (panel.call, panel.more, panel.connect, panel.subtitle):
            action_bottom = action.to_window(action.x, action.y)[1]
            assert bottom - 1 <= action_bottom
            assert action_bottom + action.height <= bottom + viewport.height + 1
        name_viewport.scroll_y = 0
        after_layout(check_name_end)

    def check_name_end(_elapsed: float) -> None:
        """Scrolling the title reveals its last line while retaining the timeline."""
        panel = app.shell._peer_panel
        name_viewport = panel.header.name_viewport
        bottom = name_viewport.to_window(name_viewport.x, name_viewport.y)[1]
        name_bottom = panel.name.to_window(panel.name.x, panel.name.y)[1]
        assert abs(name_bottom - bottom) <= 1
        controller.back()
        controller.state.snapshot = snapshot
        app.shell.render()
        after_layout(scroll_older)

    def scroll_older(_elapsed: float) -> None:
        """Moves the native viewport before selecting a genuinely visible row.

        Args:
            _elapsed: Native layout interval.
        Returns:
            None
        """
        root = app.shell._root_panel
        scroll = next(
            widget for widget in root.walk() if isinstance(widget, ScrollView)
        )
        scroll.scroll_y = 0.7
        after_layout(update)

    def update(_elapsed: float) -> None:
        """Injects only newer synthetic snapshot metadata, with no restoration by the fixture.

        Args:
            _elapsed: Native scroll-settle interval.
        Returns:
            None
        """
        root = app.shell._root_panel
        scroll = next(
            widget for widget in root.walk() if isinstance(widget, ScrollView)
        )
        bottom = scroll.to_window(*scroll.pos)[1]
        action = next(
            widget
            for widget in root.walk()
            if isinstance(widget, Action)
            and widget.focus_key[:1] == ('peer',)
            and bottom <= widget.to_window(*widget.pos)[1]
            and widget.to_window(*widget.pos)[1] + widget.height
            <= bottom + scroll.height
        )
        # A renamed alias can wrap to more lines. Its reading origin is the top.
        key, top = action.focus_key, action.to_window(action.x, action.top)[1]
        action.focus = True
        snapshot = controller.state.snapshot
        controller.state.snapshot = replace(
            snapshot,
            revision=(snapshot.revision or 0) + 1,
            conversations=[DropConversationSummaryEntry('A new conversation', 'a-new')]
            + [
                replace(
                    item,
                    alias='Renamed while focused'
                    if item.onion == key[-1]
                    else item.alias,
                )
                for item in snapshot.conversations
            ],
        )
        app.refresh()

        def verify(_elapsed: float) -> None:
            """Checks the re-created control keeps exact focus and its actual native screen position.

            Args:
                _elapsed: Native metadata/layout interval.
            Returns:
                None
            """
            current = app.shell._root_panel
            replacement = next(
                widget
                for widget in current.walk()
                if isinstance(widget, Action) and widget.focus_key == key
            )
            assert replacement.focus
            assert 'Renamed while focused' in replacement.accessible_name
            new_top = replacement.to_window(replacement.x, replacement.top)[1]
            assert abs(new_top - top) <= 1, (
                top,
                new_top,
                app.shell._root_panel.scroll.scroll_y,
            )
            assert controller.state.route.view == 'V06' and controller.client is None
            complete()

        after_layout(verify)

    after_layout(check_previews)
