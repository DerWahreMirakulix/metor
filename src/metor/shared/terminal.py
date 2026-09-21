"""Terminal-safe visible encoding for untrusted text fragments."""


def escape_terminal_text(value: str) -> str:
    """Renders terminal control characters as visible data while preserving lines.

    Args:
        value (str): Untrusted text fragment destined for terminal presentation.

    Returns:
        str: Text with C0, DEL, and C1 controls encoded visibly except newline.
    """
    escaped: list[str] = []
    for character in value:
        codepoint: int = ord(character)
        if character == '\n':
            escaped.append(character)
        elif codepoint <= 0x1F or 0x7F <= codepoint <= 0x9F:
            escaped.append(f'\\x{codepoint:02x}')
        else:
            escaped.append(character)
    return ''.join(escaped)
