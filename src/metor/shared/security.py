"""Best-effort clearing of caller-owned mutable buffers; no host capabilities."""


def secure_clear_buffer(buffer: bytearray | memoryview) -> None:
    """
    Overwrites one mutable in-memory buffer with zero bytes in place.

    Args:
        buffer (bytearray | memoryview): The mutable buffer to clear.

    Returns:
        None
    """
    view: memoryview = buffer if isinstance(buffer, memoryview) else memoryview(buffer)
    view.cast('B')[:] = b'\x00' * len(view)
