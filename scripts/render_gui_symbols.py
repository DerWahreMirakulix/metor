"""Rebuild the offline GUI icon atlas from the packaged vectors with Inkscape."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1] / 'src/metor/ui/gui/assets'
VIEWBOX = 24
CELL = 128
COLUMNS = 8
NS = 'http://www.w3.org/2000/svg'


def main() -> None:
    """Rasterize the checked-in vectors once, preserving rounded strokes and tintable edges."""
    tool = shutil.which('inkscape')
    if not tool:
        raise SystemExit('Install Inkscape to rebuild the GUI symbol atlas.')
    vectors = sorted((ROOT / 'icons').glob('*-native.svg'))
    rows = 1 << (((len(vectors) + COLUMNS - 1) // COLUMNS - 1).bit_length())
    size = (COLUMNS * CELL, rows * CELL)
    root = ET.Element(
        f'{{{NS}}}svg',
        viewBox=f'0 0 {COLUMNS * VIEWBOX} {rows * VIEWBOX}',
        color='white',
    )
    regions: dict[str, list[int]] = {}
    for index, vector in enumerate(vectors):
        row, col = divmod(index, COLUMNS)
        group = ET.SubElement(
            root, f'{{{NS}}}g', transform=f'translate({col * VIEWBOX} {row * VIEWBOX})'
        )
        group.extend(ET.parse(vector).getroot())
        regions[vector.stem.removesuffix('-native')] = [
            col * CELL,
            (rows - row - 1) * CELL,
            CELL,
            CELL,
        ]
    target = ROOT / 'icons' / 'symbols.png'
    with tempfile.TemporaryDirectory() as temp:
        svg = Path(temp) / 'symbols.svg'
        svg.write_bytes(ET.tostring(root))
        subprocess.run(
            [
                tool,
                str(svg),
                '--export-area-page',
                '--export-background=white',
                '--export-background-opacity=0',
                f'--export-width={size[0]}',
                f'--export-height={size[1]}',
                f'--export-filename={target}',
            ],
            check=True,
        )
    mapping = target.with_suffix('.atlas')
    mapping.write_text(
        json.dumps({target.name: regions}, indent=2) + '\n',
        encoding='utf-8',
        newline='\n',
    )
    manifest_file = ROOT / 'manifest.json'
    manifest = json.loads(manifest_file.read_bytes())
    for asset in (target, mapping):
        name = f'icons/{asset.name}'
        manifest['assets'] = [
            entry for entry in manifest['assets'] if entry['path'] != name
        ]
        manifest['assets'].append(
            dict(
                path=name,
                source='icons/*-native.svg via scripts/render_gui_symbols.py',
                sha256=hashlib.sha256(asset.read_bytes()).hexdigest(),
            )
        )
    manifest_file.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8',
        newline='\n',
    )


if __name__ == '__main__':
    main()
