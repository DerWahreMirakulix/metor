"""Regression tests for recursive validation at the public IPC decoder boundary."""

import dataclasses
import json
import socket
import sys
import threading
import unittest
from enum import Enum
from types import UnionType
from typing import ForwardRef, Union, get_args, get_origin, get_type_hints

from metor.client.stream import BufferedIpcEventReader
from metor.core.api import (
    BeginVoiceCommand,
    CMD_MAP,
    Delivery,
    EVENT_MAP,
    EventType,
    IpcCommand,
    IpcEvent,
    MessageDirectionCode,
    MessageOutcomeEvent,
    MessageStatusCode,
    SetSettingCommand,
)
from metor.core.daemon.managed.ipc import IpcServer
from metor.utils import Constants


class _DispatcherConfig:
    """Provides the bounded socket timeout needed by the real IPC handler."""

    @staticmethod
    def get_float(_key: object) -> float:
        """Returns a short finite timeout for the local socket probe.

        Args:
            _key (object): Ignored setting identity.

        Returns:
            float: Probe socket timeout.
        """
        return 0.1


class _DispatcherProfileManager:
    """Supplies the narrow profile surface used by ``IpcServer._handler``."""

    config = _DispatcherConfig()


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

    def test_receipt_outcome_wire_fields_are_validated_enums(self) -> None:
        """Validate receipt enums and call-context bounds without a Core fixture.

        Args:
            None
        Returns:
            None
        """
        onion = 'b' * Constants.TOR_V3_ONION_ADDRESS_LENGTH
        event = IpcEvent.from_dict(
            json.loads(
                MessageOutcomeEvent(
                    onion,
                    'receipt',
                    MessageDirectionCode.OUT,
                    Delivery.DROP,
                    MessageStatusCode.DRAFT,
                ).to_json()
            )
        )
        self.assertIs(event.delivery, Delivery.DROP)
        self.assertIs(event.status, MessageStatusCode.DRAFT)
        payload = json.loads(event.to_json())
        payload['status'] = 'invented-status'
        with self.assertRaises((TypeError, ValueError)):
            IpcEvent.from_dict(payload)
        for context in (True, 0, -1):
            with self.subTest(context=context), self.assertRaises(ValueError):
                BeginVoiceCommand(
                    onion,
                    Delivery.LIVE,
                    'context',
                    'opus',
                    context_generation=context,
                )

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

    def test_nonfinite_numbers_are_rejected_by_command_and_event_factories(
        self,
    ) -> None:
        """Typed floats and open JSON trees accept only finite JSON numbers.

        Args:
            None

        Returns:
            None
        """
        for value in (
            float('nan'),
            float('inf'),
            float('-inf'),
            json.loads('1e999'),
        ):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    IpcCommand.from_dict(
                        {
                            'command_type': 'set_setting',
                            'setting_key': 'ui.default_profile',
                            'setting_value': value,
                        }
                    )
                with self.assertRaises(TypeError):
                    IpcEvent.from_dict(
                        {
                            'event_type': 'profile_operation_result',
                            'success': True,
                            'operation_type': 'profile_created',
                            'params': {'nested': [value]},
                        }
                    )
                with self.assertRaises(TypeError):
                    IpcEvent.from_dict(
                        {
                            'event_type': 'settings_list_data',
                            'scope': 'ui',
                            'entries': [
                                {
                                    'key': 'client.ipc_timeout',
                                    'value': '1',
                                    'source': 'default',
                                    'category': 'client',
                                    'min_value': value,
                                }
                            ],
                        }
                    )

        finite = sys.float_info.max
        command = IpcCommand.from_dict(
            {
                'command_type': 'set_setting',
                'setting_key': 'client.ipc_timeout',
                'setting_value': finite,
            }
        )
        event = IpcEvent.from_dict(
            {
                'event_type': 'profile_operation_result',
                'success': True,
                'operation_type': 'profile_created',
                'params': {'finite': finite},
            }
        )
        self.assertEqual(command.setting_value, finite)
        self.assertEqual(event.params['finite'], finite)

    def test_nonfinite_outbound_message_cannot_be_serialized(self) -> None:
        """Direct construction cannot put a non-standard number on the wire.

        Args:
            None

        Returns:
            None
        """
        command = SetSettingCommand('client.ipc_timeout', float('nan'))
        with self.assertRaisesRegex(ValueError, 'JSON compliant'):
            command.to_json()

    def test_sdk_reader_rejects_nonfinite_json_tokens_and_overflow(self) -> None:
        """The production SDK decoder rejects every non-finite JSON spelling.

        Args:
            None

        Returns:
            None
        """
        for token in ('NaN', 'Infinity', '-Infinity', '1e999'):
            reader = BufferedIpcEventReader()
            reader.append_bytes(
                (
                    '{"event_type":"profile_operation_result",'
                    '"success":true,"operation_type":"profile_created",'
                    f'"params":{{"nested":[{token}]}}}}\n'
                ).encode('utf-8')
            )
            with self.subTest(token=token), self.assertRaises(TypeError):
                reader.pop_event()

    def test_daemon_dispatcher_rejects_nonfinite_command_without_callback(
        self,
    ) -> None:
        """The real local socket handler rejects overflow before domain dispatch.

        Args:
            None

        Returns:
            None
        """
        dispatched: list[IpcCommand] = []
        server = IpcServer(  # type: ignore[arg-type]
            _DispatcherProfileManager(),
            lambda command, _conn: dispatched.append(command),
        )
        daemon_side, client_side = socket.socketpair()
        client_side.settimeout(2.0)
        server._clients.append(daemon_side)
        handler = threading.Thread(target=server._handler, args=(daemon_side,))
        handler.start()
        try:
            payload = (
                b'{"command_type":"set_setting",'
                b'"request_id":"finite-check",'
                b'"setting_key":"secret-field",'
                b'"setting_value":1e999}\n'
            )
            client_side.sendall(payload)
            response = client_side.recv(4096)
            decoded = IpcEvent.from_dict(json.loads(response.decode('utf-8')))
            self.assertEqual(decoded.event_type, EventType.UNKNOWN_COMMAND)
            self.assertEqual(decoded.request_id, 'finite-check')
            self.assertNotIn(b'secret-field', response)
            self.assertEqual(dispatched, [])
        finally:
            try:
                client_side.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            handler.join(timeout=2.0)
            server.stop()
            client_side.close()
        self.assertFalse(handler.is_alive())

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
