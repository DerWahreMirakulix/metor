"""
Script for auto-generating Markdown API documentation and the JSON Schema
wire contract from the Metor IPC registries.
Enforces the DRY principle by dynamically introspecting dataclasses and Enums.
Automatically resolves project paths for the src-layout architecture and applies
Prettier formatting to the final output.
"""

# ruff: noqa: E402

import sys
import json
import inspect
import dataclasses
from collections.abc import Sequence as SequenceABC
from enum import Enum
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    ForwardRef,
    List,
    Type,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)
from types import UnionType

import nacl.pwhash


# Dynamically resolve paths to support execution from any directory
SCRIPT_DIR: Path = Path(__file__).parent.resolve()
PROJECT_ROOT: Path = SCRIPT_DIR.parent
SRC_DIR: Path = PROJECT_ROOT / 'src'


# Inject the src directory into the module search path
sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

from metor.core.api import CMD_MAP, EVENT_MAP
from metor.core.auth import (
    PIN_PASSWORD_PREFIX,
    PIN_SALT_BYTES,
    PIN_VERIFIER_BYTES,
    SESSION_AUTH_PASSWORD_PREFIX,
)
from metor.shared import Constants
from metor.versioning import IPC_PROTOCOL_MIN_SUPPORTED, IPC_PROTOCOL_VERSION
from scripts.format_generated_docs import format_document
from scripts.release.paths import API_DOC_PATH, API_SCHEMA_PATH

if TYPE_CHECKING:
    from metor.core.api import IpcMessage


class ApiDocGenerator:
    """Generates Markdown API documentation by inspecting the core IPC DTOs."""

    def __init__(self, output_path: str | Path) -> None:
        """
        Initializes the documentation generator.

        Args:
            output_path (str | Path): The absolute or relative path for the generated Markdown file.

        Returns:
            None
        """
        self._output_path: Path = Path(output_path)

    def _get_type_name(self, field_type: object) -> str:
        """
        Extracts a clean string representation of a type hint, stripping verbose typing prefixes
        and internal module paths to maintain readability in the generated documentation.

        Args:
            field_type (object): The type annotation from the dataclass field.

        Returns:
            str: The formatted stringified type.
        """
        origin: Any = get_origin(field_type)
        args: tuple[Any, ...] = get_args(field_type)

        if origin is list and args:
            return f'List[{self._get_type_name(args[0])}]'
        if origin is dict and len(args) == 2:
            return (
                f'Dict[{self._get_type_name(args[0])}, {self._get_type_name(args[1])}]'
            )
        if origin is tuple and args:
            joined_args: str = ', '.join(self._get_type_name(arg) for arg in args)
            return f'Tuple[{joined_args}]'
        if origin is not None and args:
            origin_name: str = getattr(origin, '__name__', str(origin))
            joined_args = ', '.join(self._get_type_name(arg) for arg in args)
            return f'{origin_name}[{joined_args}]'

        type_str: str = str(field_type)

        # Explicitly catch the complex JsonValue resolution
        if 'ForwardRef' in type_str and 'JsonValue' in type_str:
            return 'Dict[str, JsonValue]'

        # Handle built-in classes vs typing module classes
        if type_str.startswith("<class '") and type_str.endswith("'>"):
            type_str = type_str.split("'")[1]
            if '.' in type_str:
                type_str = type_str.split('.')[-1]

        # Strip standard typing prefixes
        type_str = type_str.replace('typing.', '')
        type_str = type_str.replace('NoneType', 'None')

        # Clean up absolute module paths for new DTO Sub-Models and Enums
        type_str = type_str.replace('metor.core.api.events.entries.', '')
        type_str = type_str.replace('metor.core.api.events.', '')
        type_str = type_str.replace('metor.core.api.events.history.', '')
        type_str = type_str.replace('metor.core.api.codes.', '')
        type_str = type_str.replace('metor.core.api.base.', '')

        return type_str

    def _sample_value(self, field_type: object) -> Any:
        """
        Builds a compact example value for a dataclass field annotation.

        Args:
            field_type (object): The dataclass field annotation.

        Returns:
            Any: A JSON-serializable sample value.
        """
        origin: Any = get_origin(field_type)
        args: tuple[Any, ...] = get_args(field_type)

        if origin in (list, SequenceABC) and args:
            return [self._sample_value(args[0])]
        if origin is dict and len(args) == 2:
            return {'key': self._sample_value(args[1])}
        if origin is tuple and args:
            return [self._sample_value(arg) for arg in args]
        if origin is not None and args:
            non_none_args: List[Any] = [arg for arg in args if arg is not type(None)]
            return self._sample_value(non_none_args[0]) if non_none_args else None
        if isinstance(field_type, type) and dataclasses.is_dataclass(field_type):
            hints: Dict[str, object] = get_type_hints(field_type)
            payload: Dict[str, Any] = {}
            for field in dataclasses.fields(field_type):
                if not field.init and isinstance(field.default, Enum):
                    payload[field.name] = field.default.value
                elif (
                    field.init
                    and field.default is dataclasses.MISSING
                    and field.default_factory is dataclasses.MISSING
                ):
                    payload[field.name] = self._sample_value(hints[field.name])
            return payload
        if isinstance(field_type, type) and issubclass(field_type, Enum):
            return next(iter(field_type)).value
        if field_type is str:
            return 'string'
        if field_type is int:
            return 0
        if field_type is float:
            return 0.0
        if field_type is bool:
            return False
        if field_type is type(None):
            return None
        raise TypeError(f'Unsupported IPC example annotation: {field_type!r}')

    def _build_example_payload(
        self,
        cls: Type['IpcMessage'],
        route_key: str,
        route_value: str,
    ) -> str:
        """
        Builds a compact JSON example for one command or event DTO.

        Args:
            cls (Type[IpcMessage]): The dataclass type to introspect.
            route_key (str): The envelope routing key.
            route_value (str): The concrete routing value.

        Returns:
            str: A formatted JSON example string.
        """
        payload: Dict[str, Any] = {route_key: route_value}
        hints: Dict[str, object] = get_type_hints(cls)

        for field in dataclasses.fields(cls):
            if field.name in ('command_type', 'event_type'):
                continue

            if (
                field.default is dataclasses.MISSING
                and field.default_factory is dataclasses.MISSING
            ):
                payload[field.name] = (
                    field.metadata['example']
                    if 'example' in field.metadata
                    else self._sample_value(hints[field.name])
                )

        return json.dumps(payload, indent=2, allow_nan=False)

    def _format_dataclass(self, cls: Type['IpcMessage']) -> str:
        """
        Extracts the fields, types, and defaults from a dataclass into a Markdown table.
        Filters out internal routing constants to reduce documentation noise.

        Args:
            cls (Type[IpcMessage]): The dataclass type to introspect.

        Returns:
            str: The formatted Markdown string for the class.
        """
        docstring: str = inspect.getdoc(cls) or 'No description provided.'
        lines: List[str] = [
            f'### `{cls.__name__}`',
            '',
            f'{docstring}',
            '',
            '| Field | Type | Default |',
            '|---|---|---|',
        ]

        field_count: int = 0
        for f in dataclasses.fields(cls):
            if f.name in ('command_type', 'event_type'):
                continue

            field_count += 1
            type_name: str = self._get_type_name(f.type)

            default_val: str = 'Required'
            if isinstance(f.default, Enum):
                default_val = f'`{f.default.__class__.__name__}.{f.default.name}`'
            elif f.default is not dataclasses.MISSING:
                default_val = f'`{f.default}`'
            elif f.default_factory is not dataclasses.MISSING:
                default_val = '`Factory()`'

            lines.append(f'| `{f.name}` | `{type_name}` | {default_val} |')

        if field_count == 0:
            lines.pop()
            lines.pop()
            lines.append('*No additional payload parameters.*')

        lines.append('')
        return '\n'.join(lines)

    @staticmethod
    def _protocol_guide() -> List[str]:
        """Describes framing, authentication and recovery for non-Python clients.

        Numeric bounds and derivation parameters come from the same public
        contract and cryptographic implementation used by the SDK.
        """
        return [
            '## Protocol Notes',
            '',
            '- Commands include a top-level `command_type`; events include `event_type`. Use the exact lowercase wire values listed below, not Python class names.',
            '- Each frame is one UTF-8 JSON object followed by a line-feed byte (`0x0a`). Buffer bytes across partial reads, split complete lines before UTF-8 decoding, and preserve coalesced frames.',
            f'- A complete frame, including its newline, must not exceed {Constants.MAX_IPC_BYTES} bytes. Apply the limit to each frame, not the sum of several bounded frames received together. Truncated EOF is not a completed response.',
            '- Types and unknown fields are strict at every nesting level. Numbers must be finite, booleans are distinct from numbers, and integer fields use integer JSON spelling. Floating-point fields also accept integer spelling. Omitted defaulted fields use their documented defaults; optional values may be null.',
            '- A malformed or unknown event ends the SDK connection. Never skip an undecodable state or authority event and keep using the old projection.',
            '- `api.schema.json` is a route/definition catalog, not a root message validator; select the route reference under `commands` or `events` to validate one complete message. Domain limits and command authorization still apply after schema validation.',
            '- IPC TCP has no transport encryption or server identity handshake. Use loopback on the trusted local host or an authenticated, encrypted SSH tunnel. Never expose or connect it directly over an untrusted network; cold unlock sends the password inside that protected transport.',
            '- Human-readable labels belong to the frontend. Branch on event types, enums and structured fields, never rendered error messages.',
            '',
            '## Canonical Client Session Sequence',
            '',
            f'The current IPC generation is **{IPC_PROTOCOL_VERSION}**; the oldest supported generation is **{IPC_PROTOCOL_MIN_SUPPORTED}**. Application release versions are independent. An overlapping generation does not promise that an older schema understands every additive capability: check `InitEvent.capabilities` before optional commands and fields.',
            '',
            '1. **Connect:** Open `127.0.0.1:<daemon_port>`, locally or through an SSH tunnel. Endpoint discovery is a host responsibility, separate from the portable wire protocol.',
            '2. **Optional local lifetime lease:** A persistent frontend attached to an automatically managed daemon sends `FrontendLeaseCommand` using its host-issued token and a random frontend ID. Independent daemons, remote endpoints and short-lived queries do not require this. The lease grants no profile access.',
            '3. **Initialize and authenticate:** Send `InitCommand(current_version=..., min_supported=...)` with a fresh `request_id`. Handle the auth gates below until `InitEvent` arrives. A locked or unauthenticated daemon may require credentials before returning Init.',
            '   - On `DaemonLockedEvent`, obtain the profile password, send `UnlockCommand` with the same request ID, and await `DaemonUnlockedEvent`. Then resend the original Init command with that request ID.',
            '   - On `AuthRequiredEvent`, derive the session proof below and send `AuthenticateSessionCommand` with the same request ID. Await `SessionAuthenticatedEvent`, then resend the original Init command. Authentication does not automatically execute the gated command.',
            '   - A failed proof may return `InvalidPasswordEvent` with a replacement challenge and salt. Use only that fresh challenge. A rate limit is a typed terminal outcome; obey `retry_after`. Cancellation, missing challenges and unrecoverable errors end the exchange.',
            '4. **Validate negotiation:** Intersect both inclusive protocol ranges and require `InitEvent.negotiated_version` to equal their highest common generation. `ProtocolMismatchEvent` or an invalid selection fails bootstrap. Complete bootstrap before concurrent application requests.',
            '5. **Subscribe and reconcile:** Send `RegisterLiveConsumerCommand`, then `GetRuntimeSnapshotCommand` for the content-free aggregate state. The registration has no success-response DTO; ordering it before the snapshot on the same socket establishes the stream boundary. `GetChatStartupStateCommand` remains the Terminal compatibility projection.',
            '6. **Event loop:** Keep one socket reader. Deliver asynchronous events while matching request results by `request_id`; replies and unrelated events may be interleaved. Install the snapshot epoch/revision before applying newer projection invalidations. Request outcomes, message media and lifecycle milestones are not discarded by that projection revision filter.',
            '',
            '## Portable Authentication Derivation',
            '',
            'Use raw Argon2 output, not a password-hash string such as PHC encoding. Password/PIN inputs are encoded as UTF-8 after the exact domain prefix is prepended; do not trim, case-fold or normalize them. Salt and challenge fields contain hexadecimal strings: decode them to bytes before cryptographic use.',
            '',
            '| Parameter | Session/password proof | Quick-unlock PIN proof |',
            '|---|---|---|',
            f'| Domain prefix | `{SESSION_AUTH_PASSWORD_PREFIX}` | `{PIN_PASSWORD_PREFIX}` |',
            '| Algorithm | Argon2i, version 1.3 | Argon2id, version 1.3 |',
            f'| Output bytes | {Constants.SESSION_AUTH_KEY_BYTES} | {PIN_VERIFIER_BYTES} |',
            f'| Salt bytes | {nacl.pwhash.argon2i.SALTBYTES} | {PIN_SALT_BYTES} |',
            f'| Time cost / iterations | {nacl.pwhash.argon2i.OPSLIMIT_SENSITIVE} | {nacl.pwhash.argon2id.OPSLIMIT_INTERACTIVE} |',
            f'| Memory bytes | {nacl.pwhash.argon2i.MEMLIMIT_SENSITIVE} | {nacl.pwhash.argon2id.MEMLIMIT_INTERACTIVE} |',
            f'| Memory KiB | {nacl.pwhash.argon2i.MEMLIMIT_SENSITIVE // 1024} | {nacl.pwhash.argon2id.MEMLIMIT_INTERACTIVE // 1024} |',
            '| Parallelism / lanes | 1 | 1 |',
            f'| Challenge bytes | {Constants.SESSION_AUTH_CHALLENGE_BYTES} | {Constants.SESSION_AUTH_CHALLENGE_BYTES} |',
            '',
            'For either method, calculate `proof = lowercase_hex(HMAC-SHA256(key=derived_key, message=hex_decode(challenge)))`. The derived key is the raw Argon2 output. In particular, the HMAC message is the decoded challenge bytes, not its hexadecimal text. Challenges are one-use and session-bound; never reuse a previous connection or restriction cycle proof.',
            '',
            'To install quick unlock, generate the random salt with a cryptographically secure generator and send its hexadecimal encoding and the hexadecimal derived PIN verifier in `ConfigureQuickUnlockCommand(action="set", ...)`. The verifier is itself an authentication credential: do not log or persist it outside protected Core storage. Configuration requires an authorized session.',
            '',
            'A `ClientRestrictedEvent` supplies the current reauthorization challenge, method and salt. Use `ReauthorizeClientCommand` for that exact session. PIN authorizes only restricted-session recovery, never a cold or hard-locked daemon. Requesting `method="profile_password"` without a proof obtains the password challenge for Forgot PIN; derive the password proof from that new challenge/salt. Core owns escalation, cooldown and effective grants.',
            '',
            '## Correlation, Failure and Reconnection',
            '',
            '- Use an opaque unique request ID for each active exchange; the SDK generates 16 random bytes as 32 lowercase hexadecimal characters. Auth follow-ups and the gated-command resend retain that exchange ID. Do not reuse an ID for overlapping requests.',
            '- Request IDs correlate responses; they are not generic mutation deduplication keys. An exchange can produce progress events before its terminal outcome. Typed rejection events are terminal; unrelated asynchronous events still belong to the event loop.',
            '- EOF, a send failure or timeout after transmission leaves a mutation outcome uncertain. Do not resend blindly. Text reconciliation uses the original `msg_id` with `GetMessageOutcomeCommand`; other operations use their exact identity and readback contract in the [frontend contract](../contracts/FRONTENDS.md).',
            '- Reconnection creates a new session: repeat Init, auth, subscription and snapshot retrieval. Previous request ownership, client restrictions and call ownership do not transfer. A runtime epoch change resets projection ordering; it does not authorize replaying a mutation.',
            f'- The Python SDK bounds pending exchanges ({Constants.MAX_PENDING_IPC_REQUESTS}), responses per exchange ({Constants.MAX_RESPONSES_PER_REQUEST}), and asynchronous queued events ({Constants.MAX_CLIENT_EVENT_QUEUE}). Stream overflow disconnects rather than dropping state. Keep callbacks short and reconcile after loss.',
            '- `MetorClient.request` returns the expected typed event, returns `None` for an incomplete auth gate or unavailable protocol/snapshot, and raises explicit transport, typed rejection or unexpected-response exceptions otherwise. A disconnect clears the cached Init event.',
            '',
        ]

    def generate(self) -> None:
        """
        Iterates over the command and event registries, builds the Markdown layout
        with a Table of Contents, and writes it to the designated file.

        Args:
            None

        Returns:
            None
        """
        sorted_commands = sorted(CMD_MAP.items(), key=lambda item: item[0].value)
        sorted_events = sorted(EVENT_MAP.items(), key=lambda item: item[0].value)

        lines: List[str] = [
            '<!-- GENERATED FILE. DO NOT EDIT MANUALLY. -->',
            '',
            '# Metor IPC API Documentation',
            '',
            'This document is auto-generated by introspecting the `metor.core.api.registry`.',
            'It describes the strict newline-delimited JSON protocol used over the local IPC socket.',
            '',
            *self._protocol_guide(),
            '## Table of Contents',
            '',
            '**Commands (UI -> Daemon)**',
        ]

        for _, cmd_cls in sorted_commands:
            cmd_anchor: str = cmd_cls.__name__.lower()
            lines.append(f'- [{cmd_cls.__name__}](#{cmd_anchor})')

        lines.extend(['', '**Events (Daemon -> UI)**'])

        for _, event_cls in sorted_events:
            evt_anchor: str = event_cls.__name__.lower()
            lines.append(f'- [{event_cls.__name__}](#{evt_anchor})')

        lines.extend(['', '## 1. Commands (UI -> Daemon)', ''])

        for index, (command_type, cmd_cls) in enumerate(sorted_commands):
            lines.append(self._format_dataclass(cmd_cls))
            lines.append(f'**Wire Value:** `{command_type.value}`')
            lines.append('')
            lines.append('**Example JSON**')
            lines.append('')
            lines.append('```json')
            lines.append(
                self._build_example_payload(
                    cmd_cls,
                    'command_type',
                    command_type.value,
                )
            )
            lines.append('```')
            if index < len(sorted_commands) - 1:
                lines.append('')
                lines.append('---')

        lines.extend(['', '## 2. Events (Daemon -> UI)', ''])

        for index, (event_type, event_cls) in enumerate(sorted_events):
            lines.append(self._format_dataclass(event_cls))
            lines.append(f'**Wire Value:** `{event_type.value}`')
            lines.append('')
            lines.append('**Example JSON**')
            lines.append('')
            lines.append('```json')
            lines.append(
                self._build_example_payload(
                    event_cls,
                    'event_type',
                    event_type.value,
                )
            )
            lines.append('```')
            if index < len(sorted_events) - 1:
                lines.append('')
                lines.append('---')

        with self._output_path.open('w', encoding='utf-8', newline='\n') as f:
            f.write('\n'.join(lines))


class ApiSchemaGenerator:
    """Generates a JSON Schema document describing the registered IPC DTOs."""

    def __init__(self, output_path: str | Path) -> None:
        """
        Initializes the schema generator.

        Args:
            output_path (str | Path): The absolute or relative path for the generated JSON Schema file.

        Returns:
            None
        """
        self._output_path: Path = Path(output_path)

    def _field_schema(self, field_type: object) -> Dict[str, Any]:
        """
        Maps one dataclass field annotation to a JSON Schema fragment.

        Unknown or unresolvable type information fails generation so published
        schemas cannot silently become more permissive than the decoder.

        Args:
            field_type (object): The type annotation from the dataclass field.

        Returns:
            Dict[str, Any]: The JSON Schema fragment for the annotation.
        """
        origin: Any = get_origin(field_type)
        args: tuple[Any, ...] = get_args(field_type)

        if isinstance(field_type, ForwardRef):
            if field_type.__forward_arg__ == 'JsonValue':
                return {'$ref': '#/definitions/JsonValue'}
            raise TypeError(f'Unsupported IPC schema forward reference: {field_type!r}')

        if origin is Union or origin is UnionType:
            member_schemas: List[Dict[str, Any]] = [
                self._field_schema(arg) for arg in args if arg is not type(None)
            ]
            if type(None) in args:
                member_schemas.append({'type': 'null'})
            if not member_schemas:
                raise TypeError(f'Empty IPC union annotation: {field_type!r}')
            return {'anyOf': member_schemas}
        if origin in (list, List, SequenceABC):
            if len(args) != 1:
                raise TypeError(f'Untyped IPC sequence annotation: {field_type!r}')
            items: Dict[str, Any] = self._field_schema(args[0])
            return {'type': 'array', 'items': items}
        if origin in (dict, Dict):
            if len(args) != 2 or self._field_schema(args[0]) != {'type': 'string'}:
                raise TypeError(
                    f'Unsupported IPC mapping key annotation: {field_type!r}'
                )
            return {
                'type': 'object',
                'additionalProperties': self._field_schema(args[1]),
            }
        if isinstance(field_type, type) and issubclass(field_type, Enum):
            enum_values: List[Any] = [member.value for member in field_type]
            schema: Dict[str, Any] = {'enum': enum_values}
            if all(isinstance(value, str) for value in enum_values):
                schema['type'] = 'string'
            return schema
        if field_type is str:
            return {'type': 'string'}
        if field_type is int:
            return {'type': 'integer'}
        if field_type is float:
            return {'type': 'number'}
        if field_type is bool:
            return {'type': 'boolean'}
        if field_type is type(None):
            return {'type': 'null'}
        if isinstance(field_type, type) and dataclasses.is_dataclass(field_type):
            return self._dto_schema(field_type)
        raise TypeError(f'Unsupported IPC schema annotation: {field_type!r}')

    def _dto_schema(self, cls: type[Any]) -> Dict[str, Any]:
        """
        Builds one JSON Schema object schema for a command or event DTO.

        Routing constants (`command_type` / `event_type`) are represented as
        required constants so one selected route definition validates a complete
        wire message. Fields without a default are listed as required.

        Args:
            cls: The registered DTO or nested public dataclass to introspect.

        Returns:
            Dict[str, Any]: The JSON Schema object schema for the DTO.
        """
        hints: Dict[str, object] = get_type_hints(cls)

        properties: Dict[str, Any] = {}
        required: List[str] = []

        for f in dataclasses.fields(cls):
            if not f.init and isinstance(f.default, Enum):
                properties[f.name] = {
                    'type': 'string',
                    'const': f.default.value,
                }
                required.append(f.name)
            else:
                properties[f.name] = self._field_schema(hints[f.name])
            if f.init and (
                f.default is dataclasses.MISSING
                and f.default_factory is dataclasses.MISSING
            ):
                required.append(f.name)

        schema: Dict[str, Any] = {
            'title': cls.__name__,
            'type': 'object',
            'properties': properties,
            'additionalProperties': False,
        }
        if required:
            schema['required'] = required
        return schema

    def generate(self) -> None:
        """
        Iterates over the command and event registries, builds the JSON Schema
        document, and writes it to the designated file.

        Args:
            None

        Returns:
            None
        """
        sorted_commands = sorted(CMD_MAP.items(), key=lambda item: item[0].value)
        sorted_events = sorted(EVENT_MAP.items(), key=lambda item: item[0].value)

        definitions: Dict[str, Any] = {
            'JsonValue': {
                'anyOf': [
                    {'type': 'string'},
                    {'type': 'integer'},
                    {'type': 'number'},
                    {'type': 'boolean'},
                    {'type': 'null'},
                    {
                        'type': 'object',
                        'additionalProperties': {'$ref': '#/definitions/JsonValue'},
                    },
                    {
                        'type': 'array',
                        'items': {'$ref': '#/definitions/JsonValue'},
                    },
                ]
            }
        }
        commands: Dict[str, Any] = {}
        events: Dict[str, Any] = {}

        for command_type, cmd_cls in sorted_commands:
            definitions[cmd_cls.__name__] = self._dto_schema(cmd_cls)
            commands[command_type.value] = {'$ref': f'#/definitions/{cmd_cls.__name__}'}

        for event_type, event_cls in sorted_events:
            definitions[event_cls.__name__] = self._dto_schema(event_cls)
            events[event_type.value] = {'$ref': f'#/definitions/{event_cls.__name__}'}

        document: Dict[str, Any] = {
            '$schema': 'https://json-schema.org/draft/2020-12/schema',
            'title': 'Metor IPC Contract',
            'description': (
                'Route and DTO definition catalog for the Metor IPC contract. '
                'Select the matching commands or events reference to validate a '
                'complete message; this catalog root is not itself a validator.'
            ),
            'definitions': definitions,
            'commands': commands,
            'events': events,
        }

        with self._output_path.open('w', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps(document, indent=2, allow_nan=False))
            f.write('\n')


def main() -> None:
    """
    Entry point for the API doc generation script.
    Generates the Markdown file and formats it using Prettier.

    Args:
        None

    Returns:
        None
    """
    output_file: Path = API_DOC_PATH
    generator: ApiDocGenerator = ApiDocGenerator(output_file)
    generator.generate()
    sys.stdout.write(
        f'API documentation successfully generated at: {output_file.absolute()}\n'
    )

    schema_file: Path = API_SCHEMA_PATH
    schema_generator: ApiSchemaGenerator = ApiSchemaGenerator(schema_file)
    schema_generator.generate()
    sys.stdout.write(
        f'IPC schema documentation successfully generated at: {schema_file.absolute()}\n'
    )

    format_document(output_file)


if __name__ == '__main__':
    main()
