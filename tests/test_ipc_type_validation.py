"""Regression tests for recursive validation at the public IPC decoder boundary."""

import dataclasses
import json
import unittest
from enum import Enum
from types import UnionType
from typing import ForwardRef, Union, get_args, get_origin, get_type_hints

from metor.client.stream import BufferedIpcEventReader
from metor.core.api import CMD_MAP, EVENT_MAP, IpcCommand, IpcEvent


def _sample_value(field_type: object) -> object:
    """Builds one minimal valid JSON-shaped value for a public DTO annotation."""
    origin = get_origin(field_type)
    args = get_args(field_type)
    if origin in (Union, UnionType):
        if type(None) in args:
            return None
        return _sample_value(args[0])
    if origin in (list, dict):
        return [] if origin is list else {}
    if origin is not None and getattr(origin, '__name__', '') == 'Sequence':
        return []
    if isinstance(field_type, type) and dataclasses.is_dataclass(field_type):
        payload = _sample_payload(field_type)
        for field in dataclasses.fields(field_type):
            if not field.init and isinstance(field.default, Enum):
                payload[field.name] = field.default.value
        return payload
    if isinstance(field_type, type) and issubclass(field_type, Enum):
        return next(iter(field_type)).value
    if field_type is str:
        return 'value'
    if field_type is int:
        return 1
    if field_type is float:
        return 1.0
    if field_type is bool:
        return False
    if isinstance(field_type, ForwardRef):
        return None
    raise AssertionError(f'No sample for annotation {field_type!r}')


def _sample_payload(dto_type: type[object]) -> dict[str, object]:
    """Builds required constructor fields for one dataclass as a wire mapping."""
    hints = get_type_hints(dto_type)
    return {
        field.name: _sample_value(hints[field.name])
        for field in dataclasses.fields(dto_type)
        if field.init
        and field.default is dataclasses.MISSING
        and field.default_factory is dataclasses.MISSING
    }


class IpcTypeValidationTests(unittest.TestCase):
    """Covers strict recursive validation through real command and event decoders."""

    def test_every_registered_dto_accepts_a_valid_wire_sample(self) -> None:
        """Every registered route accepts its JSON-shaped baseline payload."""
        for route, dto_type in CMD_MAP.items():
            payload = {
                'command_type': route.value,
                **_sample_payload(dto_type),
            }
            with self.subTest(command=route.value):
                decoded = IpcCommand.from_dict(json.loads(json.dumps(payload)))
                self.assertIsInstance(decoded, dto_type)
                self.assertEqual(
                    IpcCommand.from_dict(json.loads(decoded.to_json())), decoded
                )

        for route, dto_type in EVENT_MAP.items():
            payload = {'event_type': route.value, **_sample_payload(dto_type)}
            with self.subTest(event=route.value):
                decoded = IpcEvent.from_dict(json.loads(json.dumps(payload)))
                self.assertIsInstance(decoded, dto_type)
                self.assertEqual(
                    IpcEvent.from_dict(json.loads(decoded.to_json())), decoded
                )

    def test_integer_fields_reject_booleans_at_every_depth(self) -> None:
        """JSON booleans never satisfy integer annotations, including mappings."""
        with self.assertRaises(TypeError):
            IpcEvent.from_dict(
                {
                    'event_type': 'transport_state',
                    'peer': 'peer',
                    'session_state': 'live',
                    'focus_count': True,
                }
            )
        with self.assertRaises(TypeError):
            IpcEvent.from_dict(
                {
                    'event_type': 'inbox_data',
                    'alias': 'peer',
                    'inbox_counts': {'drop': 1, 'live': True},
                }
            )

    def test_later_list_elements_and_nested_unknown_fields_are_rejected(self) -> None:
        """Validation examines every nested item and rejects DTO schema drift."""
        base = {
            'event_type': 'contacts_data',
            'profile': 'default',
            'discovered': [],
        }
        for invalid in (
            {'alias': 'second', 'onion': 'peer', 'saved': 'yes'},
            {'alias': 'second', 'onion': 'peer', 'saved': True, 'extra': 'drift'},
        ):
            payload = {
                **base,
                'saved': [
                    {'alias': 'first', 'onion': 'peer', 'saved': True},
                    invalid,
                ],
            }
            with self.subTest(invalid=invalid), self.assertRaises(TypeError):
                IpcEvent.from_dict(payload)

    def test_voice_duration_and_content_discriminator_are_strict(self) -> None:
        """Voice duration preserves null while rejecting coercion and bad variants."""
        base = {
            'event_type': 'message_received',
            'alias': 'peer',
            'delivery': 'drop',
            'content': {
                'type': 'voice',
                'blob_id': 'blob',
                'codec': 'opus',
                'size_bytes': 12,
            },
        }
        for duration in (None, 125):
            payload = json.loads(json.dumps(base))
            payload['content']['duration_ms'] = duration
            decoded = IpcEvent.from_dict(payload)
            self.assertEqual(decoded.content.duration_ms, duration)

        for duration in ('125', True):
            payload = json.loads(json.dumps(base))
            payload['content']['duration_ms'] = duration
            with self.subTest(duration=duration), self.assertRaises(TypeError):
                IpcEvent.from_dict(payload)

        for discriminator in ('file', None):
            payload = json.loads(json.dumps(base))
            payload['content']['type'] = discriminator
            with (
                self.subTest(discriminator=discriminator),
                self.assertRaises(TypeError),
            ):
                IpcEvent.from_dict(payload)

    def test_open_json_mapping_remains_recursively_json_typed(self) -> None:
        """Open JsonValue fields accept JSON trees but reject arbitrary Python objects."""
        params = {
            'nested': [None, True, 3, 4.5, 'value', {'deeper': ['ok']}],
        }
        decoded = IpcEvent.from_dict(
            {
                'event_type': 'profile_operation_result',
                'success': True,
                'operation_type': 'profile_created',
                'params': params,
            }
        )
        self.assertEqual(decoded.params, params)

        with self.assertRaises(TypeError):
            IpcEvent.from_dict(
                {
                    'event_type': 'profile_operation_result',
                    'success': True,
                    'operation_type': 'profile_created',
                    'params': {'invalid': object()},
                }
            )

    def test_buffered_ipc_reader_applies_recursive_validation(self) -> None:
        """The production NDJSON reader rejects an invalid later nested element."""
        reader = BufferedIpcEventReader()
        reader.append_bytes(
            json.dumps(
                {
                    'event_type': 'contacts_data',
                    'profile': 'default',
                    'saved': [
                        {'alias': 'first', 'onion': 'peer', 'saved': True},
                        {'alias': 'second', 'onion': 'peer', 'saved': 1},
                    ],
                    'discovered': [],
                }
            ).encode('utf-8')
            + b'\n'
        )
        with self.assertRaises(TypeError):
            reader.pop_event()

    def test_envelope_correlation_fields_keep_strict_optional_types(self) -> None:
        """Request, epoch, and revision fields retain their nullable wire semantics."""
        decoded = IpcEvent.from_dict(
            {
                'event_type': 'daemon_unlocked',
                'request_id': None,
                'epoch': 'epoch-1',
                'revision': 7,
            }
        )
        self.assertIsNone(decoded.request_id)
        self.assertEqual(decoded.epoch, 'epoch-1')
        self.assertEqual(decoded.revision, 7)
        with self.assertRaises(TypeError):
            IpcEvent.from_dict({'event_type': 'daemon_unlocked', 'revision': True})


if __name__ == '__main__':
    unittest.main()
