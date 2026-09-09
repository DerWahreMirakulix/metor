"""Contract tests for independent message delivery and typed content."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.core.api import (
    ContentType,
    Delivery,
    IpcCommand,
    IpcEvent,
    MessageReceivedEvent,
    SendMessageCommand,
    TextContent,
)


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

    def test_generated_schema_exposes_delivery_and_content(self) -> None:
        """Verifies generated non-Python clients can implement the model.

        Args:
            None

        Returns:
            None
        """
        schema_path = Path(__file__).resolve().parents[1] / 'docs' / 'api.schema.json'
        schema = json.loads(schema_path.read_text(encoding='utf-8'))
        command_schema = schema['definitions']['SendMessageCommand']['properties']
        self.assertIn('delivery', command_schema)
        self.assertIn('content', command_schema)


if __name__ == '__main__':
    unittest.main()
