"""Current frontend-neutral contact QR validation contract."""

import base64
import hashlib
import json
import unittest

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
        )
        for raw, expected in cases:
            with self.subTest(expected=expected):
                result = validate_contact_qr(raw)
                self.assertFalse(result.valid)
                self.assertIs(result.error, expected)

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
