"""Forward-compatible Terminal rendering for typed message content."""

from metor.core.api import MessageContent, TextContent, VoiceContent


def render_content(content: MessageContent | object) -> str:
    """Renders supported content or a stable generic placeholder.

    Args:
        content (MessageContent | object): Typed or future content value.

    Returns:
        str: Terminal-safe text preserving existing Text rendering.
    """
    if isinstance(content, TextContent):
        return content.text
    if isinstance(content, VoiceContent):
        return f'[Voice: {content.codec}, {content.size_bytes} bytes]'
    return '[Unsupported message content]'
