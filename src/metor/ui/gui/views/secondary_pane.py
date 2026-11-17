"""Full detail-pane wheel input with a centered, readable secondary column."""

from kivy.input.motionevent import MotionEvent
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView


FULL_PANE_VIEWS = frozenset({'V13', 'V14', 'V15', 'V17', 'V18', 'V19', 'V20'})


class SecondaryPane(BoxLayout):
    """Let heading and padding wheel input reach this page's own viewport."""

    scroll: ScrollView

    def on_touch_down(self, touch: MotionEvent) -> bool:
        """Forward only vertical wheel events inside this foreground detail pane.

        Normal pointer/touch hit testing stays with the original child. Modal
        windows receive their input before this page; the sidebar lies outside
        its bounds. The native ScrollView still owns wheel speed and boundaries.
        """
        if (
            not self.disabled
            and touch.is_mouse_scrolling
            and touch.button in {'scrollup', 'scrolldown'}
            and self.collide_point(*touch.pos)
            and not self.scroll.collide_point(*touch.pos)
        ):
            touch.push()
            try:
                touch.apply_transform_2d(lambda x, _y: (x, self.scroll.center_y))
                return bool(self.scroll.dispatch('on_touch_down', touch))
            finally:
                touch.pop()
        return bool(super().on_touch_down(touch))
