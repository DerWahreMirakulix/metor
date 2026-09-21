"""Regression tests aligning generated IPC examples, schemas, and decoders."""

import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from metor.core.api import CMD_MAP, EVENT_MAP, IpcCommand, IpcEvent
from scripts.generate_api_docs import ApiDocGenerator, ApiSchemaGenerator
from scripts.release.compatibility import ipc_breaking_changes


_EXAMPLE_PATTERN = re.compile(
    r'### `(?P<class_name>[^`]+)`.*?'
    r'\*\*Wire Value:\*\* `(?P<route>[^`]+)`.*?'
    r'```json\n(?P<payload>\{.*?\})\n```',
    re.DOTALL,
)


def _resolve_schema(
    schema: dict[str, Any], definitions: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Resolves a local generated-schema reference."""
    reference = schema.get('$ref')
    if reference is None:
        return schema
    name = cast(str, reference).rsplit('/', maxsplit=1)[-1]
    return definitions[name]


def _schema_accepts(
    schema: dict[str, Any],
    value: object,
    definitions: dict[str, dict[str, Any]],
) -> bool:
    """Evaluates the JSON Schema subset emitted by the IPC generator."""
    schema = _resolve_schema(schema, definitions)
    alternatives = schema.get('anyOf')
    if isinstance(alternatives, list):
        return any(
            _schema_accepts(option, value, definitions)
            for option in cast(list[dict[str, Any]], alternatives)
        )
    if 'const' in schema and value != schema['const']:
        return False
    enum_values = schema.get('enum')
    if isinstance(enum_values, list) and value not in enum_values:
        return False

    schema_type = schema.get('type')
    if schema_type == 'null':
        return value is None
    if schema_type == 'string':
        return type(value) is str
    if schema_type == 'integer':
        return type(value) is int
    if schema_type == 'number':
        return type(value) in (int, float)
    if schema_type == 'boolean':
        return type(value) is bool
    if schema_type == 'array':
        return isinstance(value, list) and all(
            _schema_accepts(schema['items'], item, definitions) for item in value
        )
    if schema_type == 'object':
        if not isinstance(value, dict):
            return False
        properties = cast(dict[str, dict[str, Any]], schema.get('properties', {}))
        required = cast(list[str], schema.get('required', []))
        if any(key not in value for key in required):
            return False
        additional = schema.get('additionalProperties', True)
        for key, item in value.items():
            if key in properties:
                if not _schema_accepts(properties[key], item, definitions):
                    return False
            elif additional is False:
                return False
            elif isinstance(additional, dict) and not _schema_accepts(
                additional, item, definitions
            ):
                return False
        return True
    return False


class ApiGenerationContractTests(unittest.TestCase):
    """Covers generated examples and schemas against the strict IPC decoder."""

    def _generate(self, directory: Path) -> tuple[Path, Path]:
        """Generates both IPC reference artifacts into an isolated directory."""
        api_path = directory / 'API.md'
        schema_path = directory / 'api.schema.json'
        ApiDocGenerator(api_path).generate()
        ApiSchemaGenerator(schema_path).generate()
        return api_path, schema_path

    def test_every_documented_example_matches_decoder_and_route_schema(self) -> None:
        """All route examples decode and satisfy their concrete DTO definition."""
        with tempfile.TemporaryDirectory() as directory:
            api_path, schema_path = self._generate(Path(directory))
            api_text = api_path.read_text(encoding='utf-8')
            schema = json.loads(schema_path.read_text(encoding='utf-8'))

        definitions = schema['definitions']
        examples = list(_EXAMPLE_PATTERN.finditer(api_text))
        self.assertEqual(len(examples), len(CMD_MAP) + len(EVENT_MAP))
        for match in examples:
            route = match.group('route')
            payload = json.loads(match.group('payload'))
            if 'command_type' in payload:
                decoded = IpcCommand.from_dict(payload)
                reference = schema['commands'][route]
            else:
                decoded = IpcEvent.from_dict(payload)
                reference = schema['events'][route]
            with self.subTest(route=route):
                self.assertEqual(type(decoded).__name__, match.group('class_name'))
                dto_schema = _resolve_schema(reference, definitions)
                self.assertTrue(_schema_accepts(dto_schema, payload, definitions))

    def test_negative_container_and_discriminator_values_fail_both_contracts(
        self,
    ) -> None:
        """Decoder and schema reject the same recursive container violations."""
        with tempfile.TemporaryDirectory() as directory:
            _, schema_path = self._generate(Path(directory))
            schema = json.loads(schema_path.read_text(encoding='utf-8'))
        definitions = schema['definitions']
        cases = (
            (
                {
                    'event_type': 'inbox_data',
                    'alias': 'peer',
                    'inbox_counts': {'drop': 1, 'live': True},
                },
                'InboxDataEvent',
            ),
            (
                {
                    'event_type': 'contacts_data',
                    'profile': 'default',
                    'saved': [
                        {'alias': 'one', 'onion': 'peer', 'saved': True},
                        {'alias': 'two', 'onion': 'peer', 'saved': 1},
                    ],
                    'discovered': [],
                },
                'ContactsDataEvent',
            ),
            (
                {
                    'event_type': 'message_received',
                    'alias': 'peer',
                    'delivery': 'drop',
                    'content': {'type': 'file', 'text': 'invalid'},
                },
                'MessageReceivedEvent',
            ),
        )
        for payload, definition_name in cases:
            with self.subTest(definition=definition_name):
                with self.assertRaises(TypeError):
                    IpcEvent.from_dict(payload)
                self.assertFalse(
                    _schema_accepts(definitions[definition_name], payload, definitions)
                )

    def test_schema_is_a_strict_route_catalog_and_generation_is_stable(self) -> None:
        """The root identifies a catalog and repeated generation is byte-identical."""
        with tempfile.TemporaryDirectory() as directory:
            api_path, schema_path = self._generate(Path(directory))
            first = (api_path.read_bytes(), schema_path.read_bytes())
            self._generate(Path(directory))
            second = (api_path.read_bytes(), schema_path.read_bytes())
            schema = json.loads(second[1])
        self.assertEqual(first, second)
        self.assertIn('catalog', schema['description'].lower())
        self.assertNotIn('oneOf', schema)
        self.assertFalse(
            schema['definitions']['InboxDataEvent']['additionalProperties']
        )

    def test_unknown_annotations_fail_generation_closed(self) -> None:
        """Unsupported annotations cannot silently become permissive schemas."""
        with tempfile.TemporaryDirectory() as directory:
            generator = ApiSchemaGenerator(Path(directory) / 'schema.json')
            with self.assertRaises(TypeError):
                generator._field_schema(complex)

    def test_route_discriminators_complete_definitions_without_false_breaks(
        self,
    ) -> None:
        """Catalog routes validate full messages without inventing a wire change."""
        with tempfile.TemporaryDirectory() as directory:
            _, schema_path = self._generate(Path(directory))
            current = json.loads(schema_path.read_text(encoding='utf-8'))
        previous = copy.deepcopy(current)
        for group, route_field in (
            ('commands', 'command_type'),
            ('events', 'event_type'),
        ):
            for reference in previous[group].values():
                definition_name = reference['$ref'].rsplit('/', maxsplit=1)[-1]
                definition = previous['definitions'][definition_name]
                definition['properties'].pop(route_field)
                definition['required'].remove(route_field)
        self.assertEqual(ipc_breaking_changes(previous, current), ())

    def test_open_json_schema_accepts_only_recursive_json_values(self) -> None:
        """JsonValue mappings stay open to valid recursive JSON content."""
        with tempfile.TemporaryDirectory() as directory:
            _, schema_path = self._generate(Path(directory))
            schema = json.loads(schema_path.read_text(encoding='utf-8'))
        definitions = schema['definitions']
        params_schema = definitions['ProfileOperationResultEvent']['properties'][
            'params'
        ]
        valid = {'nested': [None, True, 1, 2.5, 'value', {'deep': []}]}
        self.assertTrue(_schema_accepts(params_schema, valid, definitions))
        invalid = copy.deepcopy(valid)
        invalid['nested'].append({'bad': object()})
        self.assertFalse(_schema_accepts(params_schema, invalid, definitions))


if __name__ == '__main__':
    unittest.main()
