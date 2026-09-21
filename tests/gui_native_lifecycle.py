"""Real Linux session-D-Bus lifecycle signal probe for an installed GUI."""

import asyncio
import importlib
import threading

from metor.ui.gui.platform.lifecycle import DesktopLifecycleEvent, LinuxLifecycleSource


async def emit(active: bool) -> None:
    """Publish one standard screen-saver transition on the real session bus."""
    message = importlib.import_module('dbus_next.message').Message
    message_bus = importlib.import_module('dbus_next.aio').MessageBus
    bus = await message_bus().connect()
    try:
        await bus.send(
            message.new_signal(
                '/org/freedesktop/ScreenSaver',
                'org.freedesktop.ScreenSaver',
                'ActiveChanged',
                'b',
                [active],
            )
        )
    finally:
        bus.disconnect()


def main() -> None:
    """Verify real subscription, delivery, resume mapping, and bounded teardown."""
    received: list[DesktopLifecycleEvent] = []
    delivered = threading.Event()

    def publish(event: DesktopLifecycleEvent) -> None:
        received.append(event)
        delivered.set()

    source = LinuxLifecycleSource(publish)
    source.start()
    try:
        asyncio.run(emit(True))
        if not delivered.wait(2.0):
            raise AssertionError('Linux lock signal was not delivered')
        delivered.clear()
        asyncio.run(emit(False))
        if not delivered.wait(2.0):
            raise AssertionError('Linux unlock signal was not delivered')
    finally:
        source.close()
    if received != [DesktopLifecycleEvent.LOCK, DesktopLifecycleEvent.RESUME]:
        raise AssertionError(f'Unexpected lifecycle sequence: {received!r}')


if __name__ == '__main__':
    main()
