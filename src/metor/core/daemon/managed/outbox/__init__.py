"""Public facade for asynchronous drop delivery."""

from .worker import OutboxWorker

__all__ = ['OutboxWorker']
