"""Contract tests for independent message delivery and typed content."""

import json
import sys
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.core.api import (
    ConnectionActor,
    ConnectionReasonCode,
    ContentType,
    Delivery,
    IpcCommand,
    IpcEvent,
    MessageReceivedEvent,
    RuntimeSnapshotEvent,
    RuntimeSnapshotUnavailableEvent,
    SendMessageCommand,
    TextContent,
    VoiceContent,
)
from metor.core.daemon.managed.handlers.network import NetworkCommandHandler
from metor.core.daemon.managed.models import SessionState
from metor.core.daemon.managed.network.state import StateTracker
from metor.ui.terminal.content import render_content
from metor.utils import Constants


class MessageArchitectureContractTests(unittest.TestCase):
    """Covers the public message model and wire representation."""

    def test_delivery_and_content_are_independent_and_round_trip(self) -> None:
        """Verifies both delivery values carry the same typed content.

        Args:
            None

        Returns:
            None
        """
        content = TextContent('hello')
        for delivery in Delivery:
            command = SendMessageCommand('peer', delivery, content, 'msg-1')
            decoded = IpcCommand.from_dict(json.loads(command.to_json()))
            self.assertIsInstance(decoded, SendMessageCommand)
            self.assertIs(decoded.delivery, delivery)
            self.assertEqual(decoded.content, content)
            self.assertIs(decoded.content.type, ContentType.TEXT)

    def test_received_message_round_trips_typed_content(self) -> None:
        """Verifies generic inbound events retain delivery and content.

        Args:
            None

        Returns:
            None
        """
        event = MessageReceivedEvent(
            alias='peer',
            delivery=Delivery.LIVE,
            content=TextContent('hello'),
            msg_id='msg-1',
        )
        decoded = IpcEvent.from_dict(json.loads(event.to_json()))
        self.assertEqual(decoded, event)

    def test_voice_content_round_trips_without_text_assumptions(self) -> None:
        """Preserves opaque Voice metadata through the strict union decoder."""
        content = VoiceContent(
            blob_id='ab' * 32,
            codec='opus',
            size_bytes=4096,
            duration_ms=750,
        )
        event = MessageReceivedEvent(
            alias='peer',
            delivery=Delivery.LIVE,
            content=content,
            msg_id='voice-1',
        )
        decoded = IpcEvent.from_dict(json.loads(event.to_json()))
        self.assertEqual(decoded, event)
        self.assertEqual(render_content(content), '[Voice: opus, 4096 bytes]')
        self.assertEqual(render_content(object()), '[Unsupported message content]')

    def test_generated_schema_exposes_delivery_and_content(self) -> None:
        """Verifies generated non-Python clients can implement the model.

        Args:
            None

        Returns:
            None
        """
        schema_path = (
            Path(__file__).resolve().parents[1]
            / 'docs'
            / 'generated'
            / 'api.schema.json'
        )
        schema = json.loads(schema_path.read_text(encoding='utf-8'))
        command_schema = schema['definitions']['SendMessageCommand']['properties']
        self.assertIn('delivery', command_schema)
        self.assertIn('content', command_schema)

    def test_runtime_snapshot_retries_across_revision_change(self) -> None:
        """Installs only a snapshot candidate built during a stable event epoch."""
        handler = cast(Any, object.__new__(NetworkCommandHandler))
        revisions = iter((4, 5, 5, 5))
        compose_count = 0

        def compose() -> RuntimeSnapshotEvent:
            nonlocal compose_count
            compose_count += 1
            return RuntimeSnapshotEvent(profile='default', onion='peer-onion')

        handler._current_revision = lambda: next(revisions)
        handler._compose_runtime_snapshot = compose
        handler._network = Mock()
        handler._network.get_snapshot_token.return_value = ('stable',)

        snapshot = handler._build_runtime_snapshot()

        self.assertEqual(compose_count, 2)
        self.assertEqual(snapshot.revision, 5)

    def test_runtime_snapshot_exhaustion_is_explicitly_retryable(self) -> None:
        """G20: sustained mutation cannot produce an unchecked snapshot."""
        handler = cast(Any, object.__new__(NetworkCommandHandler))
        revisions = iter(range(Constants.RUNTIME_SNAPSHOT_MAX_RETRIES * 2))
        handler._current_revision = lambda: next(revisions)
        handler._network = Mock()
        handler._network.get_snapshot_token.return_value = ('stable',)
        handler._compose_runtime_snapshot = lambda: RuntimeSnapshotEvent(
            profile='default', onion='peer-onion'
        )

        result = handler._build_runtime_snapshot()

        self.assertIsInstance(result, RuntimeSnapshotUnavailableEvent)
        self.assertTrue(cast(RuntimeSnapshotUnavailableEvent, result).retryable)

    def test_runtime_snapshot_retries_when_state_mutates_before_publication(
        self,
    ) -> None:
        """R2-T22: a stable revision alone cannot bless a torn state snapshot."""
        handler = cast(Any, object.__new__(NetworkCommandHandler))
        handler._current_revision = lambda: 9
        tokens = iter((('before',), ('after',), ('stable',), ('stable',)))
        handler._network = Mock()
        handler._network.get_snapshot_token.side_effect = lambda: next(tokens)
        compose_count = 0

        def compose() -> RuntimeSnapshotEvent:
            nonlocal compose_count
            compose_count += 1
            return RuntimeSnapshotEvent(profile='default', onion='peer')

        handler._compose_runtime_snapshot = compose
        result = handler._build_runtime_snapshot()
        self.assertEqual(compose_count, 2)
        self.assertEqual(result.revision, 9)

    def test_snapshot_state_distinguishes_recovery_and_terminal_disconnect(
        self,
    ) -> None:
        """R2-T24: recovery grace/scheduling are not projected as disconnected."""
        state = StateTracker()
        state.mark_live_reconnect_grace('grace', 30.0)
        state.mark_scheduled_auto_reconnect('scheduled')
        state.set_last_disconnect_reason(
            'terminal',
            ConnectionReasonCode.IDLE_TIMEOUT,
            ConnectionActor.SYSTEM,
        )

        self.assertIs(state.get_live_state('grace'), SessionState.RECONNECT_GRACE)
        self.assertIs(
            state.get_live_state('scheduled'), SessionState.RECONNECT_SCHEDULED
        )
        self.assertIs(state.get_live_state('terminal'), SessionState.DISCONNECTED)
        self.assertEqual(
            state.get_last_disconnect_reason('terminal'),
            ConnectionReasonCode.IDLE_TIMEOUT,
        )
        self.assertIn('terminal', state.get_relevant_live_onions())


if __name__ == '__main__':
    unittest.main()
