"""Deterministic response/event demultiplexing regressions for the public client."""

# ruff: noqa: E402

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.client.ipc import IpcClient
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
        client = IpcClient(
            port=1,
            timeout=0.1,
            on_event=asynchronous.append,
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


if __name__ == '__main__':
    unittest.main()
