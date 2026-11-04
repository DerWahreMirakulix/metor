"""Checks packaged fallback selection and asset integrity without a native toolkit."""

import hashlib
import json
from pathlib import Path
import unittest

from metor.ui.gui.theme import ASSET_ROOT, font_path, initial_font


class GuiFontTests(unittest.TestCase):
    """Keeps Unicode display coverage offline and independent of canonical text."""

    def test_primary_text_and_real_fallback_weights(self) -> None:
        """Selects redistributable fonts without pretending to cover every Unicode glyph.

        Args:
            None
        Returns:
            None
        """
        self.assertEqual(
            Path(font_path(600, 'Metor äöü Ελληνικά')).name, 'InterTight-600.ttf'
        )
        self.assertEqual(Path(font_path(400, 'שלום')).name, 'DejaVuSans.ttf')
        self.assertEqual(Path(font_path(600, 'שלום')).name, 'DejaVuSans-Bold.ttf')
        self.assertEqual(Path(font_path(400, '漢字')).name, 'DejaVuSans.ttf')
        self.assertEqual(Path(font_path(400, 'text\ntext')).name, 'InterTight-400.ttf')

    def test_initials_require_glyphs_in_the_selected_bundled_face(self) -> None:
        """Missing glyphs use the local contact artwork rather than a missing-glyph box."""
        self.assertEqual(initial_font('MC'), font_path(600, 'MC'))
        self.assertEqual(initial_font('É'), font_path(600, 'É'))
        self.assertEqual(initial_font('ש'), font_path(600, 'ש'))
        self.assertIsNone(initial_font('漢'))

    def test_all_recorded_assets_match_packaged_hashes(self) -> None:
        """Pins font/license/coverage and existing icon provenance to shipped bytes.

        Args:
            None
        Returns:
            None
        """
        manifest = json.loads((ASSET_ROOT / 'manifest.json').read_text())
        for asset in manifest['assets']:
            with self.subTest(path=asset['path']):
                path = ASSET_ROOT / asset['path']
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(), asset['sha256']
                )


if __name__ == '__main__':
    unittest.main()
