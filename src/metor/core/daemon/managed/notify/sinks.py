"""
Module defining the built-in file and webhook notification sinks.

FileSink appends JSON-Lines records under a lock and flushes after every write;
WebhookSink POSTs JSON with a short timeout and swallows every failure so a
notification can never crash the daemon. Both sink factories are registered
into the shared sink-type registry on import.
"""

import json
import threading
from dataclasses import asdict
from typing import Dict
from urllib.request import Request, urlopen

from metor.core.api import JsonValue

# Local Package Imports
from metor.core.daemon.managed.notify.notification import (
    NotificationPayload,
    Sink,
    register_sink_type,
)


WEBHOOK_TIMEOUT_SECONDS: float = 5.0


class FileSink:
    """Appends each notification as one JSON-Lines record under a lock, flushing after write."""

    def __init__(self, path: str) -> None:
        """Initializes the FileSink.

        Args:
            path (str): The target JSON-Lines file path.

        Returns:
            None
        """
        self._path: str = path
        self._lock: threading.Lock = threading.Lock()

    def deliver(self, payload: NotificationPayload) -> None:
        """Appends one serialized payload as a JSON-Lines record.

        Args:
            payload (NotificationPayload): The structured payload to persist.

        Returns:
            None
        """
        record: str = json.dumps(asdict(payload), ensure_ascii=False)
        with self._lock:
            with open(self._path, 'a', encoding='utf-8') as handle:
                handle.write(record)
                handle.write('\n')
                handle.flush()


class WebhookSink:
    """POSTs each notification as JSON to a webhook URL; failures are swallowed silently."""

    def __init__(self, url: str) -> None:
        """Initializes the WebhookSink.

        Args:
            url (str): The webhook endpoint URL.

        Returns:
            None
        """
        self._url: str = url

    def deliver(self, payload: NotificationPayload) -> None:
        """POSTs the serialized payload to the webhook URL without raising.

        Args:
            payload (NotificationPayload): The structured payload to deliver.

        Returns:
            None
        """
        try:
            body: bytes = json.dumps(asdict(payload), ensure_ascii=False).encode(
                'utf-8'
            )
            request = Request(
                self._url,
                data=body,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with urlopen(request, timeout=WEBHOOK_TIMEOUT_SECONDS) as response:
                response.read()
        except Exception:
            pass


def file_sink_factory(config: Dict[str, JsonValue]) -> Sink:
    """Builds a FileSink from a sink configuration dict.

    Args:
        config (Dict[str, JsonValue]): The parsed sink configuration.

    Raises:
        ValueError: If the config lacks a non-empty 'path' string.

    Returns:
        Sink: The constructed FileSink.
    """
    path: JsonValue = config.get('path')
    if not isinstance(path, str) or not path:
        raise ValueError("File sink config requires a non-empty 'path' string.")
    return FileSink(path)


def webhook_sink_factory(config: Dict[str, JsonValue]) -> Sink:
    """Builds a WebhookSink from a sink configuration dict.

    Args:
        config (Dict[str, JsonValue]): The parsed sink configuration.

    Raises:
        ValueError: If the config lacks a non-empty 'url' string.

    Returns:
        Sink: The constructed WebhookSink.
    """
    url: JsonValue = config.get('url')
    if not isinstance(url, str) or not url:
        raise ValueError("Webhook sink config requires a non-empty 'url' string.")
    return WebhookSink(url)


register_sink_type('file', file_sink_factory)
register_sink_type('webhook', webhook_sink_factory)
