"""Current frontend-neutral contact QR validation contract."""

import base64
import hashlib
import json
import unittest
from unittest.mock import patch

from metor.client import ContactQrError, validate_contact_qr


def address(value: int) -> str:
    """Builds a valid Tor v3 identity from fixed nonsecret bytes."""
    public = bytes([value]) * 32
    checksum = hashlib.sha3_256(b'.onion checksum' + public + b'\x03').digest()[:2]
    return base64.b32encode(public + checksum + b'\x03').decode('ascii').lower()


class ContactQrContractTests(unittest.TestCase):
    """Pins the SDK contract consumed by both current frontends."""

    def test_rejects_malformed_extended_and_unknown_version_payloads(self) -> None:
        """Untrusted scanner input fails with stable, non-ambiguous error codes."""
        cases = (
            (b'\xff', ContactQrError.MALFORMED),
            ('[]', ContactQrError.MALFORMED),
            (
                '{"version":1,"onion":"peer","extra":true}',
                ContactQrError.INVALID_FIELDS,
            ),
            ('{"version":2,"onion":"peer"}', ContactQrError.UNSUPPORTED_VERSION),
            ('{"version":true,"onion":"peer"}', ContactQrError.UNSUPPORTED_VERSION),
            ('{"version":1.0,"onion":"peer"}', ContactQrError.UNSUPPORTED_VERSION),
            ('{"version":1,"version":2}', ContactQrError.MALFORMED),
            (
                '{"version":' + '[' * 1200 + '1' + ']' * 1200 + '}',
                ContactQrError.MALFORMED,
            ),
            (' ' * 4100, ContactQrError.MALFORMED),
            ('\ud800', ContactQrError.MALFORMED),
        )
        for raw, expected in cases:
            with self.subTest(expected=expected):
                result = validate_contact_qr(raw)
                self.assertFalse(result.valid)
                self.assertIs(result.error, expected)

    def test_nested_containers_are_rejected_before_json_decoding(self) -> None:
        """Depth rejection must be independent of the Python parser's recursion budget."""
        with patch('metor.client.contact_qr.json.loads') as decode:
            for nested in ([1], {'note': 'value'}):
                self.assertIs(
                    validate_contact_qr(json.dumps({'version': nested})).error,
                    ContactQrError.MALFORMED,
                )
            decode.assert_not_called()

    def test_quoted_delimiters_and_escaped_quotes_in_alias_are_plain_text(self) -> None:
        """Braces in a legal string, including after an escaped quote, are data."""
        alias = 'Alice "A" {[peer]} \\'
        contact = json.dumps({'version': 1, 'onion': address(17), 'alias': alias})
        result = validate_contact_qr(contact)
        assert result.payload is not None
        self.assertEqual(result.payload.alias, alias)

    def test_accepts_version_one_identity_and_normalizes_fields(self) -> None:
        """A valid payload yields the canonical onion suffix and trimmed alias."""
        onion = address(17)
        result = validate_contact_qr(
            json.dumps({'version': 1, 'onion': onion, 'alias': '  Alice  '}).encode()
        )
        self.assertTrue(result.valid)
        self.assertIsNone(result.error)
        self.assertIsNotNone(result.payload)
        assert result.payload is not None
        self.assertEqual(result.payload.version, 1)
        self.assertEqual(result.payload.onion, onion + '.onion')
        self.assertEqual(result.payload.alias, 'Alice')


if __name__ == '__main__':
    unittest.main()
