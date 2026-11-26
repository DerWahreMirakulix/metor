"""Best-effort clearing of caller-owned mutable buffers; no host capabilities."""


def secure_clear_buffer(buffer: bytearray | memoryview) -> None:
    """
    Overwrites one mutable in-memory buffer with zero bytes in place.

    Args:
        buffer (bytearray | memoryview): The mutable buffer to clear.

    Returns:
        None

    Raises:
        TypeError: If the supplied view is read-only.
        BufferError: If the supplied view is not C-contiguous.
    """
    view: memoryview = buffer if isinstance(buffer, memoryview) else memoryview(buffer)
    if view.readonly:
        raise TypeError('Cannot clear a read-only memory view.')
    if not view.c_contiguous:
        raise BufferError('Cannot clear a non-contiguous memory view.')

    byte_view = view.cast('B')
    byte_view[:] = b'\x00' * byte_view.nbytes
