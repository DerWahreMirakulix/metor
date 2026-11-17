"""Keep redirected CLI output portable across native process encodings."""

import io
import sys


def configure_redirected_output() -> bool:
    """Select UTF-8 for actual output pipes while preserving terminal handling.

    Valid Unicode is emitted unchanged; isolated surrogate code points in host
    diagnostics are escaped rather than causing an encoding failure. Custom
    streams remain the caller's responsibility. Failure to configure a real output
    stream prevents command dispatch without exposing exception details.

    Returns:
        bool: Whether both standard output streams can retain this contract.
    """
    try:
        for stream in (sys.stdout, sys.stderr):
            if isinstance(stream, io.TextIOWrapper) and not stream.isatty():
                stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    except (OSError, ValueError):
        return False
    return True
