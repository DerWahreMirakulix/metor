"""Native Core-backed secondary navigation without injected action results."""

import time
from typing import TYPE_CHECKING

from kivy.metrics import dp
from kivy.uix.scrollview import ScrollView

from gui_native_x11 import rectangle
from metor.core.api import Delivery
from metor.ui.gui.constants import Geometry
from metor.ui.gui.widgets import Action
from metor.ui.gui.widgets.qr import ContactQr

if TYPE_CHECKING:
    from gui_native_core import NativeCoreApp


SCROLL_SETTLE_SECONDS = 0.4
SCROLL_STEPS = 8
GEOMETRY_TOLERANCE = 1.0


class NativeSecondaryProbe:
    """Checks one-click secondary routes and persistent desktop master navigation."""

    def __init__(self, app: 'NativeCoreApp') -> None:
        """Keeps only fixture timing and the application that owns native input."""
        self.app = app
        self.last_scroll = 0.0
        self.clicked_at = 0.0

    def add_steps(self) -> None:
        """Extends the real SDK/Core journey before the ordinary settings exit."""
        app = self.app
        app.add(
            'settings_profiles_native_click',
            lambda: app.route('V17') and self.reachable('Profiles'),
            lambda: app.click('Profiles'),
        )
        app.add(
            'profiles_my_contact_single_click',
            lambda: app.route('V20') and self.reachable('My contact'),
            self.open_my_contact,
        )
        app.add('my_contact_visible_without_other_activity', self.qr_visible, self.back)
        app.add(
            'my_contact_back_returns_profiles',
            lambda: app.route('V20'),
            lambda: app.click('Back'),
        )
        app.add('profiles_back_returns_settings', lambda: app.route('V17'))
        if app.args.width >= Geometry.BREAKPOINT:
            app.add('settings_master_live_click', lambda: app.route('V17'), self.live)
            app.add('settings_master_live_visible', self.live_visible, self.drop)
            app.add('settings_master_drop_visible', self.drop_visible, self.chat)
            app.add(
                'settings_chat_opens_on_first_click',
                lambda: app.route('V08') and app.peer() is not None,
                lambda: app.click('Settings'),
            )
            app.add('settings_reopened_from_peer', lambda: app.route('V17'))

    def reachable(self, name: str) -> bool:
        """Scrolls through native wheel input until the complete target is visible."""
        app = self.app
        action = app.action(name)
        if action is None or action.disabled or app.native._wheel:
            return False
        scroll = next(
            (
                item
                for item in app.scope().walk(restrict=True)
                if isinstance(item, ScrollView)
                and action in tuple(item.walk(restrict=True))
            ),
            None,
        )
        if scroll is None:
            return True
        _, bottom, _, height = rectangle(action)
        _, lower, _, viewport = rectangle(scroll)
        if (
            bottom >= lower - GEOMETRY_TOLERANCE
            and bottom + height <= lower + viewport + GEOMETRY_TOLERANCE
        ):
            return True
        now = time.monotonic()
        if now - self.last_scroll >= SCROLL_SETTLE_SECONDS:
            app.native.scroll(scroll, downward=bottom < lower, steps=SCROLL_STEPS)
            self.last_scroll = now
        return False

    def open_my_contact(self) -> None:
        """Clicks the real profile action once without an explicit fixture repaint."""
        self.clicked_at = time.monotonic()
        self.app.click('My contact')

    def qr_visible(self) -> bool:
        """Requires the controller route and the attached native QR to agree."""
        return bool(
            self.app.route('V15')
            and self.app.shell is not None
            and any(isinstance(item, ContactQr) for item in self.app.shell.walk())
        )

    def back(self) -> None:
        """Records observed navigation time and returns through the native Back action."""
        self.app.ux.records['my_contact_single_click'] = {
            'click_to_observation_ms': round(
                (time.monotonic() - self.clicked_at) * 1000, 3
            ),
            'additional_clicks': 0,
            'fixture_refresh': False,
        }
        self.app.capture('my-contact')
        self.app.click('Back')

    def master(self, delivery: Delivery) -> bool:
        """Requires selected master mode, accent action and retained Settings detail."""
        app = self.app
        root = app.shell._root_panel if app.shell is not None else None
        return bool(
            app.route('V17')
            and root is not None
            and root.delivery is delivery
            and root.tabs[delivery].surface == delivery.value + 'Surface'
            and root.new.surface == delivery.value
            and root.new._tone == 'onAccent'
            and root.tabs[delivery].width >= dp(Geometry.TARGET)
        )

    def live(self) -> None:
        """Selects the real persistent master tab while Settings stays open."""
        assert self.master(Delivery.DROP)
        self.app.click('LIVE')

    def live_visible(self) -> bool:
        """Observes the active Live master without changing the detail route."""
        return self.master(Delivery.LIVE)

    def drop(self) -> None:
        """Returns to the DROP master through a single native tab click."""
        self.app.click('DROP')

    def drop_visible(self) -> bool:
        """Observes the restored DROP master and the unchanged Settings detail."""
        return self.master(Delivery.DROP)

    def chat(self) -> None:
        """Opens an existing conversation once directly from the Settings sidebar."""
        assert self.app.shell is not None
        root = self.app.shell._root_panel
        assert root is not None
        row = root.rows[self.app.target]
        assert isinstance(row.action, Action)
        self.app.native.click(row.action)
