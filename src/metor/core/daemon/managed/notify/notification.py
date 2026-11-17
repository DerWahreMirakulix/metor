"""
Module defining the detached notification payload, sink protocol, and sink-type registry.

Notifications are structured, UI-agnostic payloads delivered to configurable sinks
(file, webhook, or UI-registered custom types) whenever the daemon operates without
connected UI clients. The registry allows UI developers to register additional sink
types without touching the daemon core.
"""

import json
from collections import deque
import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Protocol

from metor.core.api import JsonValue


@dataclass(frozen=True)
class NotificationPayload:
    """One structured, UI-agnostic notification emitted for detached delivery.

    Attributes:
        kind (str): The notification kind, e.g. 'inbox_notification' or 'incoming_connection'.
        peer_alias (Optional[str]): The peer alias when available.
        peer_onion (Optional[str]): The peer onion address when available.
        count (int): The number of events summarized by this notification.
        timestamp (str): ISO-8601 timestamp of the triggering event.
        details (Dict[str, JsonValue]): Additional structured, JSON-safe metadata.
    """

    kind: str
    peer_alias: Optional[str] = None
    peer_onion: Optional[str] = None
    count: int = 0
    timestamp: str = ''
    details: Dict[str, JsonValue] = field(default_factory=dict)


class Sink(Protocol):
    """Protocol every notification sink must implement."""

    def deliver(self, payload: NotificationPayload) -> None:
        """Delivers one notification payload.

        Args:
            payload (NotificationPayload): The structured payload to deliver.

        Returns:
            None
        """
        ...


SinkFactory = Callable[[Dict[str, JsonValue]], Sink]

_SINK_TYPES: Dict[str, SinkFactory] = {}


def register_sink_type(sink_type: str, factory: SinkFactory) -> None:
    """Registers one sink factory under a stable type key.

    Args:
        sink_type (str): The unique sink type identifier (e.g. 'file', 'webhook').
        factory (SinkFactory): Callable building a sink from a JSON config dict.

    Raises:
        ValueError: If the sink type is already registered.

    Returns:
        None
    """
    if sink_type in _SINK_TYPES:
        raise ValueError(f"Sink type '{sink_type}' is already registered.")
    _SINK_TYPES[sink_type] = factory


def get_sink_type(sink_type: str) -> SinkFactory:
    """Returns the factory registered for one sink type.

    Args:
        sink_type (str): The sink type identifier to look up.

    Raises:
        ValueError: If the sink type is not registered.

    Returns:
        SinkFactory: The registered sink factory.
    """
    try:
        return _SINK_TYPES[sink_type]
    except KeyError:
        raise ValueError(f"Unknown sink type '{sink_type}'.") from None


def build_sink(config: Dict[str, JsonValue]) -> Sink:
    """Builds one sink instance from a JSON sink configuration dict.

    Args:
        config (Dict[str, JsonValue]): The parsed sink configuration containing a 'type' field.

    Raises:
        ValueError: If the config lacks a non-empty string 'type' field or the type is unknown.

    Returns:
        Sink: The constructed sink instance.
    """
    sink_type: JsonValue = config.get('type')
    if not isinstance(sink_type, str) or not sink_type:
        raise ValueError("Sink config requires a non-empty 'type' string.")
    return get_sink_type(sink_type)(config)


class NotificationService:
    """Delivers detached notifications through the configured sink.

    Reads the raw `daemon.notification_sink` setting via an injected getter,
    rebuilds the sink whenever the configuration changes, and swallows every
    failure so notification delivery can never crash the daemon.
    """

    def __init__(
        self,
        config_getter: Callable[[], str],
        error_callback: Optional[Callable[[str], None]] = None,
        *,
        queue_limit: int = 64,
        stop_timeout: float = 1.0,
    ) -> None:
        """Initializes the NotificationService.

        Args:
            config_getter (Callable[[], str]): Returns the current `daemon.notification_sink` string.
            error_callback (Optional[Callable[[str], None]]): Optional console-safe error sink.
            queue_limit: Maximum transient payload records awaiting the one worker.
            stop_timeout: Maximum seconds spent joining a blocked optional sink.

        Returns:
            None
        """
        self._config_getter: Callable[[], str] = config_getter
        self._error_callback: Optional[Callable[[str], None]] = error_callback
        if queue_limit < 1 or stop_timeout < 0:
            raise ValueError('Notification queue bounds must be positive')
        self._condition = threading.Condition()
        self._queue: deque[NotificationPayload] = deque()
        self._queue_limit = queue_limit
        self._stop_timeout = stop_timeout
        self._closed = False
        self._overloaded = False
        self._cached_raw: Optional[str] = None
        self._cached_sink: Optional[Sink] = None
        self._worker = threading.Thread(
            target=self._run,
            name='metor-notification-sink',
            daemon=True,
        )
        self._worker.start()

    def dispatch(self, payload: NotificationPayload) -> None:
        """Delivers one payload through the configured sink, defensively.

        Args:
            payload (NotificationPayload): The structured payload to deliver.

        Returns:
            None
        """
        with self._condition:
            if self._closed:
                return
            if len(self._queue) >= self._queue_limit:
                self._overloaded = True
            else:
                self._queue.append(payload)
            self._condition.notify()

    def _run(self) -> None:
        """Resolve and deliver on one finite worker outside domain callers.

        Args:
            None

        Returns:
            None
        """
        while True:
            payload = None
            overloaded = False
            with self._condition:
                while not self._closed and not self._queue and not self._overloaded:
                    self._condition.wait()
                if self._closed:
                    self._queue.clear()
                    return
                overloaded, self._overloaded = self._overloaded, False
                if self._queue:
                    payload = self._queue.popleft()
            if overloaded:
                self._report('Notification sink queue is full; notification dropped')
            if payload is None:
                continue
            sink = self._resolve_sink()
            if sink is None:
                continue
            try:
                sink.deliver(payload)
            except Exception:
                self._report('Notification sink delivery failed')

    def close(self) -> None:
        """Drop pending optional work and wait only a configured finite interval.

        Args:
            None

        Returns:
            None
        """
        with self._condition:
            self._closed = True
            self._queue.clear()
            self._overloaded = False
            self._condition.notify_all()
        self._worker.join(self._stop_timeout)

    def _resolve_sink(self) -> Optional[Sink]:
        """Resolves the cached sink for the current setting value.

        Args:
            None

        Returns:
            Optional[Sink]: The configured sink, or None when disabled or misconfigured.
        """
        try:
            raw: str = self._config_getter()
            if not raw.strip():
                self._cached_raw = None
                self._cached_sink = None
                return None
            if raw == self._cached_raw:
                return self._cached_sink
            parsed: object = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError('sink config must be a JSON object')
            self._cached_sink = build_sink(parsed)
            self._cached_raw = raw
            return self._cached_sink
        except Exception:
            self._cached_raw = None
            self._cached_sink = None
            self._report('Invalid notification sink configuration')
            return None

    def _report(self, message: str) -> None:
        """Forwards one console-safe failure message to the error callback.

        Args:
            message (str): The failure description.

        Returns:
            None
        """
        if self._error_callback is None:
            return
        try:
            self._error_callback(message)
        except Exception:
            pass
