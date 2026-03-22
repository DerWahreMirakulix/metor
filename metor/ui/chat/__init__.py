"""
Package initializer for the interactive Chat User Interface.
Exposes only the main Chat engine to the outside application.
"""

from metor.ui.chat.engine import ChatEngine as Chat

__all__ = ['Chat']
