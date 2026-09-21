"""Bounded optional notification delivery and rejected-socket cleanup."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import unittest
from unittest.mock import Mock, patch

from metor.core.daemon.managed.ipc import IpcServer
from metor.core.daemon.managed.notify.notification import (
    NotificationPayload,
    NotificationService,
)
from metor.core.daemon.managed.notify.sinks import WebhookSink


class NotificationDeliveryTests(unittest.TestCase):
    """Keeps optional sink latency and failures outside messaging callers."""

    def test_webhook_never_reads_an_unbounded_response_body(self) -> None:
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.side_effect = AssertionError('response body must not be read')

        with patch(
            'metor.core.daemon.managed.notify.sinks.urlopen', return_value=response
        ):
            WebhookSink('http://127.0.0.1/hook').deliver(
                NotificationPayload('inbox_notification')
            )

        response.read.assert_not_called()

    def test_webhook_returns_after_headers_from_slow_large_local_response(self) -> None:
        """A local endpoint cannot retain delivery by streaming a huge body."""
        headers_sent, allow_body, returned = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )

        class Handler(BaseHTTPRequestHandler):
            """Controlled endpoint that withholds a declared large response body."""

            def do_POST(self) -> None:
                length = int(self.headers.get('Content-Length', '0'))
                self.rfile.read(length)
                self.send_response(200)
                self.send_header('Content-Length', str(8 * 1024 * 1024))
                self.end_headers()
                headers_sent.set()
                allow_body.wait(2)
                try:
                    self.wfile.write(b'x' * (8 * 1024 * 1024))
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, _format: str, *args: object) -> None:
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        serving = threading.Thread(target=server.serve_forever)
        serving.start()
        caller = threading.Thread(
            target=lambda: (
                WebhookSink(
                    f'http://127.0.0.1:{server.server_address[1]}/hook'
                ).deliver(NotificationPayload('inbox_notification')),
                returned.set(),
            )
        )
        caller.start()
        try:
            self.assertTrue(headers_sent.wait(1))
            self.assertTrue(returned.wait(0.5))
        finally:
            allow_body.set()
            caller.join(2)
            server.shutdown()
            server.server_close()
            serving.join(2)

    def test_slow_sink_never_blocks_dispatch_caller(self) -> None:
        entered, release, returned = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        sink = Mock()

        def block(_payload: NotificationPayload) -> None:
            entered.set()
            release.wait(2)

        sink.deliver.side_effect = block
        with patch(
            'metor.core.daemon.managed.notify.notification.build_sink',
            return_value=sink,
        ):
            service = NotificationService(
                lambda: json.dumps({'type': 'controlled'}), stop_timeout=0.05
            )
            caller = threading.Thread(
                target=lambda: (
                    service.dispatch(NotificationPayload('incoming_connection')),
                    returned.set(),
                )
            )
            caller.start()
            try:
                self.assertTrue(returned.wait(0.2))
                self.assertTrue(entered.wait(1))
            finally:
                release.set()
                caller.join(1)
                service.close()

    def test_queue_full_drops_new_work_and_reports_without_payload_data(self) -> None:
        entered, release, reported = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        errors: list[str] = []
        sink = Mock()

        def block(_payload: NotificationPayload) -> None:
            entered.set()
            release.wait(2)

        def report(message: str) -> None:
            errors.append(message)
            reported.set()

        sink.deliver.side_effect = block
        with patch(
            'metor.core.daemon.managed.notify.notification.build_sink',
            return_value=sink,
        ):
            service = NotificationService(
                lambda: json.dumps({'type': 'controlled'}),
                report,
                queue_limit=1,
                stop_timeout=0.05,
            )
            service.dispatch(NotificationPayload('first', peer_alias='private'))
            self.assertTrue(entered.wait(1))
            service.dispatch(NotificationPayload('second', peer_alias='secret'))
            service.dispatch(NotificationPayload('third', peer_alias='more-secret'))
            release.set()
            self.assertTrue(reported.wait(1))
            service.close()

        self.assertLessEqual(sink.deliver.call_count, 2)
        self.assertTrue(any('queue' in message.lower() for message in errors))
        self.assertNotIn('secret', ' '.join(errors))
        self.assertNotIn('private', ' '.join(errors))

    def test_close_drops_pending_and_waits_only_the_configured_bound(self) -> None:
        entered, release = threading.Event(), threading.Event()
        sink = Mock()
        sink.deliver.side_effect = lambda _payload: (entered.set(), release.wait(2))
        with patch(
            'metor.core.daemon.managed.notify.notification.build_sink',
            return_value=sink,
        ):
            service = NotificationService(
                lambda: json.dumps({'type': 'controlled'}),
                queue_limit=2,
                stop_timeout=0.01,
            )
            service.dispatch(NotificationPayload('active'))
            self.assertTrue(entered.wait(1))
            service.dispatch(NotificationPayload('must-drop'))
            service.close()
            self.assertEqual(sink.deliver.call_count, 1)
            release.set()
            service.close()


class IpcRejectCleanupTests(unittest.TestCase):
    """Freshly rejected sockets always relinquish their descriptor."""

    def test_send_failure_still_closes_rejected_client(self) -> None:
        server = object.__new__(IpcServer)
        server._stamp_revision = Mock()
        conn = Mock()
        conn.sendall.side_effect = OSError('peer reset')

        server._reject_client_limit(conn, 1)

        conn.close.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
