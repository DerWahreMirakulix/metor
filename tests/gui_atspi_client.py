"""External AT-SPI client for the isolated native accessibility privacy fixture."""

from pathlib import Path
import sys
import time

from gi.repository import Gio, GLib


def main(folder: Path) -> None:
    """Queries only the private fixture bus, then checks retained-node revocation.

    Args:
        folder: Test synchronization directory on an isolated D-Bus session.
    Returns:
        None
    """
    session = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    session.call_sync(
        'org.a11y.Bus',
        '/org/a11y/bus',
        'org.freedesktop.DBus.Properties',
        'Set',
        GLib.Variant(
            '(ssv)', ('org.a11y.Status', 'ScreenReaderEnabled', GLib.Variant('b', True))
        ),
        None,
        Gio.DBusCallFlags.NONE,
        5000,
        None,
    )
    address = session.call_sync(
        'org.a11y.Bus',
        '/org/a11y/bus',
        'org.a11y.Bus',
        'GetAddress',
        None,
        None,
        Gio.DBusCallFlags.NONE,
        5000,
        None,
    ).unpack()[0]
    bus = Gio.DBusConnection.new_for_address_sync(
        address,
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
        | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
        None,
        None,
    )

    def call(
        destination: str,
        path: str,
        interface: str,
        method: str,
        args: GLib.Variant | None = None,
    ) -> object:
        """Uses bounded synchronous RPC in the external fixture process only.

        Args:
            destination: Isolated accessible bus owner.
            path: Native accessible object path.
            interface: AT-SPI or Properties interface.
            method: Exact read operation.
            args: Typed optional arguments.
        Returns:
            object: Decoded native response.
        """
        return bus.call_sync(
            destination,
            path,
            interface,
            method,
            args,
            None,
            Gio.DBusCallFlags.NONE,
            5000,
            None,
        ).unpack()

    def name(destination: str, path: str) -> str:
        """Reads the native accessible name without any application-side shortcut.

        Args:
            destination: Bus owner.
            path: Native object path.
        Returns:
            str: Current native accessible name.
        """
        return call(
            destination,
            path,
            'org.freedesktop.DBus.Properties',
            'Get',
            GLib.Variant('(ss)', ('org.a11y.atspi.Accessible', 'Name')),
        )[0]

    found: tuple[str, str] | None = None
    button: tuple[str, str] | None = None
    editor: tuple[str, str] | None = None
    for _ in range(100):
        pending = [('org.a11y.atspi.Registry', '/org/a11y/atspi/accessible/root')]
        visited: set[tuple[str, str]] = set()
        while pending and len(visited) < 100:
            destination, path = pending.pop()
            if (destination, path) in visited:
                continue
            visited.add((destination, path))
            current = name(destination, path)
            if 'fixture-secret' in current:
                raise AssertionError('Secret exposed in AT-SPI name')
            if current == 'Password':
                interfaces = call(
                    destination, path, 'org.a11y.atspi.Accessible', 'GetInterfaces'
                )[0]
                if 'org.a11y.atspi.Text' in interfaces:
                    secret_text = call(
                        destination,
                        path,
                        'org.a11y.atspi.Text',
                        'GetText',
                        GLib.Variant('(ii)', (0, -1)),
                    )[0]
                    if secret_text:
                        raise AssertionError(
                            'Password content or length exposed in native AT-SPI text'
                        )
            if current == 'Fixture private alias':
                found = destination, path
            if current == 'Fixture action':
                button = destination, path
            if current == 'Fixture editor':
                editor = destination, path
            children = call(
                destination, path, 'org.a11y.atspi.Accessible', 'GetChildren'
            )[0]
            pending.extend(children)
        if found is not None:
            break
        time.sleep(0.1)
    if found is None:
        raise AssertionError('Private fixture label absent from native AT-SPI tree')
    if button is None:
        raise AssertionError('Native action missing')
    call(*button, 'org.a11y.atspi.Action', 'DoAction', GLib.Variant('(i)', (0,)))
    for _ in range(100):
        if (folder / 'invoked').exists():
            break
        time.sleep(0.1)
    else:
        raise AssertionError('Native invocation did not reach the current control')
    if editor is None:
        raise AssertionError('Native editor missing')
    call(*editor, 'org.a11y.atspi.Component', 'GrabFocus')
    for _ in range(100):
        if (folder / 'focused').exists():
            break
        time.sleep(0.1)
    else:
        raise AssertionError('Native focus did not reach the current field')
    (folder / 'before').write_text('read', encoding='utf-8')
    for _ in range(100):
        if (folder / 'covered').exists():
            break
        time.sleep(0.1)
    else:
        raise AssertionError('Cover timeout')
    try:
        retained = name(*found)
    except GLib.Error:
        retained = ''
    if retained == 'Fixture private alias':
        raise AssertionError('Retained native AT-SPI node exposed private alias')
    print('NATIVE_ATSPI_PRIVACY_OK')


if __name__ == '__main__':
    main(Path(sys.argv[1]))
