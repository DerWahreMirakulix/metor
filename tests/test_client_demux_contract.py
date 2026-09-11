"""Deterministic response/event demultiplexing regressions for the public client."""

# ruff: noqa: E402

import json
import socket
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.client.ipc import IpcClient, IpcDisconnectedError
from metor.core.api import (
    AckEvent,
    IpcEvent,
    RuntimeSnapshotEvent,
    RuntimeStateChangedEvent,
)


class ClientDemuxContractTests(unittest.TestCase):
    """Covers the sole-reader request correlation boundary."""

    def test_event_before_snapshot_response_is_not_discarded(self) -> None:
        """G21: unsolicited revisions survive a synchronous snapshot request."""
        asynchronous: list[IpcEvent] = []
        delivered = threading.Event()

        def on_event(event: IpcEvent) -> None:
            asynchronous.append(event)
            delivered.set()

        client = IpcClient(
            port=1,
            timeout=0.1,
            on_event=on_event,
            on_disconnect=lambda: None,
        )
        client.begin_request('snapshot-request')
        changed = RuntimeStateChangedEvent(
            scope='messages', revision=8, epoch='epoch-1'
        )
        snapshot = RuntimeSnapshotEvent(
            profile='default',
            onion='peer',
            request_id='snapshot-request',
            revision=7,
            epoch='epoch-1',
        )

        client._dispatch_event(changed)
        client._dispatch_event(snapshot)

        self.assertIs(client.wait_for_response('snapshot-request'), snapshot)
        self.assertTrue(delivered.wait(timeout=0.2))
        self.assertEqual(asynchronous, [changed])
        client.end_request('snapshot-request')

    def test_concurrent_request_ids_receive_only_their_own_response(self) -> None:
        """G21: concurrent request correlation does not compete for socket reads."""
        client = IpcClient(
            port=1,
            timeout=0.1,
            on_event=lambda _event: None,
            on_disconnect=lambda: None,
        )
        client.begin_request('left')
        client.begin_request('right')
        right = AckEvent(msg_id='right-message', request_id='right')
        left = AckEvent(msg_id='left-message', request_id='left')
        client._dispatch_event(right)
        client._dispatch_event(left)

        self.assertIs(client.wait_for_response('left'), left)
        self.assertIs(client.wait_for_response('right'), right)
        client.end_request('left')
        client.end_request('right')

    def test_epoch_round_trips_as_sequence_reset_boundary(self) -> None:
        """G20: daemon restart epochs survive strict event serialization."""
        original = RuntimeSnapshotEvent(
            profile='default', onion='peer', revision=1, epoch='new-daemon'
        )
        decoded = IpcEvent.from_dict(json.loads(original.to_json()))
        self.assertEqual(decoded.epoch, 'new-daemon')
        self.assertEqual(decoded.revision, 1)

    def test_concurrent_first_requests_start_exactly_one_reader(self) -> None:
        """R2-T27: serialized startup cannot create competing socket readers."""
        client = IpcClient(1, 0.2, lambda _event: None, lambda: None)
        client._socket = Mock()

        class _Thread:
            def __init__(self, **_kwargs: object) -> None:
                self.alive = False

            def start(self) -> None:
                self.alive = True

            def is_alive(self) -> bool:
                return self.alive

        barrier = threading.Barrier(3)

        def begin(request_id: str) -> None:
            barrier.wait()
            client.begin_request(request_id)

        left = threading.Thread(target=begin, args=('left',))
        right = threading.Thread(target=begin, args=('right',))
        with patch('metor.client.ipc.threading.Thread', side_effect=_Thread) as factory:
            left.start()
            right.start()
            barrier.wait()
            left.join()
            right.join()

        self.assertEqual(factory.call_count, 2)
        self.assertEqual(client._response_waiters, {'left', 'right'})

    def test_connection_loss_wakes_every_waiter_and_reconnect_resets_state(
        self,
    ) -> None:
        """R2-T27: loss is explicit for all waiters and a new stream starts clean."""
        disconnected = threading.Event()
        client = IpcClient(1, 1.0, lambda _event: None, disconnected.set)
        client.begin_request('left')
        client.begin_request('right')
        failures: list[type[BaseException]] = []
        ready = threading.Barrier(3)

        def wait(request_id: str) -> None:
            ready.wait()
            try:
                client.wait_for_response(request_id)
            except BaseException as exc:
                failures.append(type(exc))

        left = threading.Thread(target=wait, args=('left',))
        right = threading.Thread(target=wait, args=('right',))
        left.start()
        right.start()
        ready.wait()
        client._notify_disconnect()
        left.join(timeout=1.0)
        right.join(timeout=1.0)

        self.assertEqual(failures, [IpcDisconnectedError, IpcDisconnectedError])
        self.assertTrue(disconnected.wait(timeout=0.2))
        with client._response_condition:
            client._connection_lost = False
            client._response_waiters.clear()
            client._responses.clear()
        client.begin_request('new-stream')
        response = AckEvent(msg_id='new', request_id='new-stream')
        client._dispatch_event(response)
        self.assertIs(client.wait_for_response('new-stream'), response)

    def test_disconnect_callback_reconnect_starts_fresh_generation_workers(
        self,
    ) -> None:
        """C07: callback reconnect cannot reuse the reader, queue, or old workers."""
        reconnected = threading.Event()
        delivered = threading.Event()
        socket_two = Mock()
        socket_two.recv.side_effect = socket.timeout

        client: IpcClient

        def on_disconnect() -> None:
            self.assertTrue(client.connect())
            reconnected.set()

        client = IpcClient(
            1,
            0.1,
            lambda _event: delivered.set(),
            on_disconnect,
        )
        client._generation = 1
        client.start_listener()
        old_reader = client._reader
        old_queue = client._event_queue

        with patch('metor.client.ipc.socket.socket', return_value=socket_two):
            client._notify_disconnect(1, event_queue=old_queue)
            self.assertTrue(reconnected.wait(timeout=1.0))

        self.assertEqual(client._generation, 2)
        self.assertEqual(client._event_generation, 2)
        self.assertEqual(client._listener_generation, 2)
        self.assertIsNot(client._reader, old_reader)
        self.assertIsNot(client._event_queue, old_queue)
        client._dispatch_event(AckEvent(msg_id='new-generation'), 2)
        self.assertTrue(delivered.wait(timeout=1.0))
        client.stop()


if __name__ == '__main__':
    unittest.main()
