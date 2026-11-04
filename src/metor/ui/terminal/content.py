"""Forward-compatible Terminal rendering for typed message content."""

from metor.core.api import MessageContent, TextContent, VoiceContent
from metor.shared import escape_terminal_text


VOICE_HINT = 'Voice message received. Playback is not supported in this frontend.'


def render_content(content: MessageContent | object) -> str:
    """Renders supported content or a stable generic placeholder.

    Args:
        content (MessageContent | object): Typed or future content value.

    Returns:
        str: Terminal-safe text preserving existing Text rendering.
    """
    if isinstance(content, TextContent):
        return escape_terminal_text(content.text)
    if isinstance(content, VoiceContent):
        return VOICE_HINT
    return '[Unsupported message content]'
