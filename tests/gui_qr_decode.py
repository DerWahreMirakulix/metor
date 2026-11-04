"""Independent QR acceptance on an unchanged native framebuffer; optional validation-only tools."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path

from PIL import Image
import zxingcpp

from metor.client import validate_contact_qr
from metor.shared import clean_onion


def main() -> None:
    """Decodes a native image without modifying it and validates the exact public contact format.

    Args:
        None
    Returns:
        None
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--expected-contact', required=True)
    parser.add_argument('--result', type=Path, required=True)
    args = parser.parse_args()
    with Image.open(args.image) as rendered:
        results = zxingcpp.read_barcodes(
            rendered, formats=zxingcpp.BarcodeFormat.QRCode
        )
    assert len(results) == 1, 'Native framebuffer must contain one decodable QR'
    result = validate_contact_qr(results[0].text)
    assert result.payload is not None
    assert clean_onion(result.payload.onion) == clean_onion(args.expected_contact)
    evidence = {
        'kind': 'independent QR decoding of unchanged native framebuffer',
        'image': args.image.name,
        'sha256': hashlib.sha256(args.image.read_bytes()).hexdigest(),
        'decoder': 'zxing-cpp ' + importlib.metadata.version('zxing-cpp'),
        'reader': 'Pillow ' + importlib.metadata.version('pillow'),
        'decoded_exact_supported_contact': True,
        'camera': False,
        'physical_input': False,
        'image_modified': False,
    }
    args.result.write_text(json.dumps(evidence, indent=2) + '\n')
    print('NATIVE_QR_INDEPENDENT_DECODE_OK')


if __name__ == '__main__':
    main()
