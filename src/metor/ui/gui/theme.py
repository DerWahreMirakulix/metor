"""Native visual tokens and bundled asset lookup for layout v1.0."""

from functools import lru_cache
import json
from pathlib import Path


ASSET_ROOT: Path = Path(__file__).parent / 'assets'
COLORS: dict[str, str] = {
    'background': '#101619',
    'surface': '#171F22',
    'raised': '#202A2E',
    'line': '#334247',
    'text': '#F3F7F6',
    'textSecondary': '#9AA9AD',
    'textDisabled': '#68777B',
    'drop': '#4ED7C8',
    'dropSurface': '#123B38',
    'live': '#FFB454',
    'liveSurface': '#432E16',
    'danger': '#FF6474',
    'dangerSurface': '#471E27',
    'success': '#72D68C',
    'info': '#78AFFF',
    'lock': '#C5B4FF',
    'lockSurface': '#332B48',
    'onAccent': '#070A0B',
    'focus': '#4ED7C8',
    'controlBoundary': '#68777B',
}
TYPE: dict[str, tuple[int, int, int]] = {
    'hero': (28, 34, 600),
    'title': (23, 28, 600),
    'peer': (20, 26, 600),
    'row': (17, 22, 600),
    'body': (15, 20, 400),
    'button': (14, 20, 600),
    'support': (13, 18, 400),
    'caption': (12, 16, 500),
    'meta': (11, 14, 500),
    'wordmark': (18, 22, 700),
    'timer': (16, 22, 500),
}


def color(name: str) -> tuple[float, float, float, float]:
    """Returns one named RGBA token without importing the renderer.

    Args:
        name: Normative palette role.
    Returns:
        tuple[float, float, float, float]: Normalized opaque color.
    """
    value = COLORS[name].lstrip('#')
    return (
        int(value[:2], 16) / 255,
        int(value[2:4], 16) / 255,
        int(value[4:], 16) / 255,
        1.0,
    )


@lru_cache(maxsize=1)
def _primary_glyphs() -> frozenset[int]:
    """Loads fixed packaged font coverage without retaining any displayed text.

    Args:
        None
    Returns:
        frozenset[int]: Codepoints covered by all four packaged primary weights.
    """
    path = ASSET_ROOT / 'fonts' / 'InterTight-coverage.json'
    ranges: list[list[int]] = json.loads(path.read_text(encoding='utf-8'))
    return frozenset(value for start, end in ranges for value in range(start, end + 1))


def font_path(weight: int = 400, text: str = '') -> str:
    """Requires the packaged production font instead of silently substituting.

    Args:
        weight: Packaged upright weight.
        text: Display text used only for glyph selection; never cached or altered.
    Returns:
        str: Local font file for the native text renderer.
    """
    primary = _primary_glyphs()
    fallback = any(
        ord(character) >= 32 and ord(character) not in primary for character in text
    )
    name = (
        ('DejaVuSans-Bold.ttf' if weight >= 600 else 'DejaVuSans.ttf')
        if fallback
        else f'InterTight-{weight}.ttf'
    )
    path = ASSET_ROOT / 'fonts' / name
    if not path.is_file():
        raise RuntimeError('Metor font assets are missing; reinstall metor-ui-gui')
    return str(path)
