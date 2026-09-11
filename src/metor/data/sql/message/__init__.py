"""Centralized durable message persistence."""

from .repository import MessageReceiptRow, MessageRepository

__all__ = ['MessageReceiptRow', 'MessageRepository']
