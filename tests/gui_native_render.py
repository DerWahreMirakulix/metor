"""Native framebuffer viewport capture without replaying a subtree in another GL context."""

from pathlib import Path

from kivy.core.image import Image
from kivy.core.window import Window
from kivy.graphics.opengl import glReadPixels, GL_RGBA, GL_UNSIGNED_BYTE
from kivy.graphics.texture import Texture
from kivy.uix.widget import Widget


def capture_viewport(widget: Widget, path: Path) -> None:
    """Captures the actual native window region after drawing its complete canvas.

    Replaying a subtree into an offscreen FBO can inherit cached stencil state
    from a different viewport. Reading the normal native frame preserves the
    same clipping, transforms and render order as the application window.

    Args:
        widget: Visible native region, excluding documentation chrome.
        path: Destination evidence image.
    Returns:
        None
    """
    Window.dispatch('on_draw')
    x, y = widget.to_window(*widget.pos)
    width, height = int(widget.width), int(widget.height)
    assert (
        0 <= x and 0 <= y and x + width <= Window.width and y + height <= Window.height
    )
    pixels = glReadPixels(int(x), int(y), width, height, GL_RGBA, GL_UNSIGNED_BYTE)
    texture = Texture.create(size=(width, height), colorfmt='rgba')
    texture.blit_buffer(pixels, colorfmt='rgba', bufferfmt='ubyte')
    Image(texture).save(str(path), flipped=True)
