"""Contract tests for independent message delivery and typed content."""

import json
import sys
import unittest
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.core.api import (
    ContentType,
    Delivery,
    IpcCommand,
    IpcEvent,
    MessageReceivedEvent,
    RuntimeSnapshotEvent,
    SendMessageCommand,
    TextContent,
    VoiceContent,
)
from metor.core.daemon.managed.handlers.network import NetworkCommandHandler
from metor.ui.terminal.content import render_content


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

        snapshot = handler._build_runtime_snapshot()

        self.assertEqual(compose_count, 2)
        self.assertEqual(snapshot.revision, 5)


if __name__ == '__main__':
    unittest.main()
