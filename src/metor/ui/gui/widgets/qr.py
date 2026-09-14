"""Offline native contact QR drawing with integer modules and an explicit quiet zone."""

import json
import math

from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.widget import Widget
import qrcode

from metor.client import validate_contact_qr


class ContactQr(Widget):
    """Renders validated own public contact data as black integer-aligned modules."""

    def __init__(self, onion: str) -> None:
        """Builds only a supported public contact encoding without any remote execution.

        Args:
            onion: Current profile's public address.
        Returns:
            None
        """
        super().__init__(size_hint_y=None, height=dp(240))
        raw = json.dumps({'version': 1, 'onion': onion}, separators=(',', ':'))
        result = validate_contact_qr(raw)
        if result.payload is None:
            raise ValueError('Own contact identity is unavailable')
        qr = qrcode.QRCode(
            border=4, box_size=1, error_correction=qrcode.constants.ERROR_CORRECT_M
        )
        qr.add_data(raw)
        qr.make(fit=True)
        self.modules: list[list[bool]] = qr.get_matrix()
        self.bind(size=self._draw, pos=self._draw)
        self._draw()

    def _draw(self, *_args: object) -> None:
        """Draws modules on integer native pixel boundaries with no decorative overlay.

        Args:
            _args: Native geometry changes.
        Returns:
            None
        """
        self.canvas.clear()
        count = len(self.modules)
        unit = math.floor(min(self.width, self.height, dp(240)) / count)
        if unit < 1:
            return
        size = count * unit
        left, bottom = round(self.center_x - size / 2), round(self.center_y - size / 2)
        with self.canvas:
            Color(1, 1, 1, 1)
            Rectangle(pos=(left, bottom), size=(size, size))
            Color(0, 0, 0, 1)
            for row, modules in enumerate(self.modules):
                for column, filled in enumerate(modules):
                    if filled:
                        Rectangle(
                            pos=(
                                left + column * unit,
                                bottom + (count - row - 1) * unit,
                            ),
                            size=(unit, unit),
                        )
