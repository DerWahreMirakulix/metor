"""Bounded incremental terminal bytes and semantic key sequence decoding."""

import codecs

from metor.ui.terminal.constants import Constants


_ESCAPE_KEYS: dict[str, str] = {
    '\x1b[A': 'SPECIAL:UP',
    '\x1b[B': 'SPECIAL:DOWN',
    '\x1b[C': 'SPECIAL:RIGHT',
    '\x1b[D': 'SPECIAL:LEFT',
    '\x1b[H': 'SPECIAL:HOME',
    '\x1b[F': 'SPECIAL:END',
    '\x1b[1~': 'SPECIAL:HOME',
    '\x1b[4~': 'SPECIAL:END',
    '\x1b[3~': 'SPECIAL:DELETE',
}
_PASTE_BEGIN: str = '\x1b[200~'
_PASTE_END: str = '\x1b[201~'
_CONTROL_KEYS: frozenset[str] = frozenset(
    ('\r', '\n', '\x0e', '\x03', '\x04', '\x7f', '\b')
)


class KeyStream:
    """Decode input independently of OS read boundaries without retaining a paste.

    UTF-8 keeps only its incomplete code point. CSI keeps a finite bounded
    prefix; a bracketed paste streams directly into presentation tokens while
    retaining at most the incomplete terminator. Unknown CSI keys are ignored.
    """

    def __init__(self) -> None:
        """Initialize decoder state without touching any terminal or system resource."""
        self._decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self._escape = ''
        self._paste = False
        self._paste_suffix = ''
        self._paste_skip_lf = False
        self._skip_lf = False

    def feed(self, data: bytes) -> list[str]:
        """Return key/paste tokens for one arbitrary UTF-8 terminal byte chunk."""
        tokens: list[str] = []
        text: list[str] = []

        def flush_text() -> None:
            """Coalesce printable input without turning embedded controls into text."""
            if text:
                value = ''.join(text)
                tokens.append(f'PASTE:{value}' if len(value) > 1 else value)
                text.clear()

        for character in self._decoder.decode(data):
            if self._paste:
                self._paste_suffix += character
                while self._paste_suffix and not _PASTE_END.startswith(
                    self._paste_suffix
                ):
                    pasted_character = self._paste_suffix[0]
                    self._paste_suffix = self._paste_suffix[1:]
                    if self._paste_skip_lf:
                        self._paste_skip_lf = False
                        if pasted_character == '\n':
                            continue
                    if pasted_character == '\r':
                        text.append('\n')
                        self._paste_skip_lf = True
                    else:
                        text.append(pasted_character)
                if self._paste_suffix == _PASTE_END:
                    # Even a one-character newline in paste must not submit.
                    if text:
                        tokens.append('PASTE:' + ''.join(text))
                        text.clear()
                    self._paste_suffix = ''
                    self._paste = False
                    self._paste_skip_lf = False
                continue
            if self._escape:
                self._escape += character
                if self._escape in ('\x1b\r', '\x1b\n'):
                    tokens.append('SPECIAL:NEWLINE')
                    self._escape = ''
                elif self._escape == _PASTE_BEGIN:
                    self._paste = True
                    self._paste_skip_lf = False
                    self._escape = ''
                elif self._escape.startswith('\x1b['):
                    if len(self._escape) > len('\x1b[') and '@' <= character <= '~':
                        key = _ESCAPE_KEYS.get(self._escape)
                        if key is not None:
                            tokens.append(key)
                        self._escape = ''
                    elif len(self._escape) >= Constants.INPUT_ESCAPE_SEQUENCE_CHARS:
                        self._escape = ''
                else:
                    self._escape = ''
                    text.append(character)
                continue
            if self._skip_lf:
                self._skip_lf = False
                if character == '\n':
                    continue
            if character == '\x1b':
                flush_text()
                self._escape = character
            elif character in _CONTROL_KEYS:
                flush_text()
                if character == '\x0e':
                    tokens.append('SPECIAL:NEWLINE')
                elif character in ('\r', '\n'):
                    tokens.append('\n')
                    self._skip_lf = character == '\r'
                else:
                    tokens.append(character)
            else:
                text.append(character)
        if self._paste and text:
            tokens.append('PASTE:' + ''.join(text))
        else:
            flush_text()
        return tokens
