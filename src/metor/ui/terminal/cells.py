"""Unicode terminal cell geometry shared by presentation and input rendering."""

import re

from wcwidth import iter_graphemes, wcswidth


_SGR: re.Pattern[str] = re.compile(r'\x1b\[[0-9;]*m')


def cell_width(text: str) -> int:
    """Measure one visible line, excluding frontend-owned ANSI color sequences.

    Callers escape untrusted terminal controls before presentation. Wide glyphs,
    combining marks and joined emoji use Unicode terminal cells, with ambiguous
    characters occupying one cell independently of host locale.
    """
    plain = _SGR.sub('', text)
    width = wcswidth(plain)
    return width if width >= 0 else len(plain)


def line_end(text: str, columns: int) -> tuple[int, int]:
    """Return the final zero-based row and column of one auto-wrapped line.

    A full final row retains ``column == columns`` to represent pending terminal
    autowrap. Wide graphemes move together to the next row when they do not fit.
    """
    rows = cell_rows(text, columns)
    return len(rows) - 1, min(max(1, columns), cell_width(rows[-1]))


def cell_rows(text: str, columns: int) -> list[str]:
    """Split escaped plain text into physical rows without splitting graphemes.

    Explicit newlines advance once even after a full row. A full final row
    retains pending autowrap, matching ``line_end``; callers materialize a final
    empty cursor row when needed. Frontend color sequences are omitted.
    """
    columns = max(1, columns)
    rows: list[str] = []
    for logical_line in _SGR.sub('', text).split('\n'):
        row: list[str] = []
        column = 0
        for grapheme in iter_graphemes(logical_line):
            width = min(columns, cell_width(grapheme))
            if width and column + width > columns:
                rows.append(''.join(row))
                row = []
                column = 0
            row.append(grapheme)
            column += width
        rows.append(''.join(row))
    return rows
