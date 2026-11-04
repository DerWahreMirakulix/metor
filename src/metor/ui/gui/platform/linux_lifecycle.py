"""Validated Linux D-Bus provider and session binding for GUI lifecycle events."""

from dataclasses import dataclass
import os
from typing import Any


@dataclass(frozen=True)
class LinuxLifecycleSignal:
    """One validated provider signal or a provider-generation loss.

    Args:
        source_lost (bool): Whether a trusted provider changed ownership.
        interface (str | None): Validated lifecycle interface.
        member (str | None): Validated lifecycle member.
        body (list[Any]): Validated list-shaped signal payload.
    """

    source_lost: bool
    interface: str | None = None
    member: str | None = None
    body: list[Any] | None = None


class LinuxLifecycleBinding:
    """Own exact logind/session provider identities and D-Bus match rules."""

    LOGIN_SERVICE = 'org.freedesktop.login1'
    LOGIN_MANAGER_PATH = '/org/freedesktop/login1'
    LOGIN_MANAGER_INTERFACE = 'org.freedesktop.login1.Manager'
    LOGIN_SESSION_INTERFACE = 'org.freedesktop.login1.Session'
    DBUS_SERVICE = 'org.freedesktop.DBus'
    DBUS_PATH = '/org/freedesktop/DBus'
    DBUS_INTERFACE = 'org.freedesktop.DBus'
    SCREEN_SAVER_SERVICES = (
        (
            'org.freedesktop.ScreenSaver',
            '/org/freedesktop/ScreenSaver',
            'org.freedesktop.ScreenSaver',
        ),
        (
            'org.gnome.ScreenSaver',
            '/org/gnome/ScreenSaver',
            'org.gnome.ScreenSaver',
        ),
        (
            'org.cinnamon.ScreenSaver',
            '/org/cinnamon/ScreenSaver',
            'org.cinnamon.ScreenSaver',
        ),
    )

    def __init__(self, signal_message_type: object) -> None:
        """Create an empty binding for one dbus-next message-type generation.

        Args:
            signal_message_type (object): Exact dbus-next SIGNAL enum value.

        Returns:
            None
        """
        self._signal_message_type = signal_message_type
        self._trusted_routes: set[tuple[str, str, str, str]] = set()
        self._service_owners: dict[str, str] = {}

    @staticmethod
    async def _call(
        bus: Any,
        constants: Any,
        message_type: type[Any],
        **fields: Any,
    ) -> Any:
        """Call one D-Bus method and require a successful method reply.

        Args:
            bus (Any): Connected D-Bus adapter.
            constants (Any): Imported dbus-next constants module.
            message_type (type[Any]): Imported dbus-next Message class.
            **fields (Any): Exact method-call message fields.

        Returns:
            Any: Successful D-Bus reply.
        """
        reply = await bus.call(message_type(**fields))
        if reply.message_type != constants.MessageType.METHOD_RETURN:
            raise OSError('Linux lifecycle D-Bus method was rejected')
        return reply

    @classmethod
    async def _name_owner(
        cls,
        bus: Any,
        constants: Any,
        message_type: type[Any],
        service: str,
    ) -> str:
        """Resolve one well-known service to its current unique sender.

        Args:
            bus (Any): Connected D-Bus adapter.
            constants (Any): Imported dbus-next constants module.
            message_type (type[Any]): Imported dbus-next Message class.
            service (str): Well-known provider name.

        Returns:
            str: Current unique owner name.
        """
        reply = await cls._call(
            bus,
            constants,
            message_type,
            destination=cls.DBUS_SERVICE,
            path=cls.DBUS_PATH,
            interface=cls.DBUS_INTERFACE,
            member='GetNameOwner',
            signature='s',
            body=[service],
        )
        if len(reply.body) != 1 or type(reply.body[0]) is not str or not reply.body[0]:
            raise OSError('Linux lifecycle provider has no unique owner')
        return reply.body[0]

    @classmethod
    async def _add_match(
        cls,
        bus: Any,
        constants: Any,
        message_type: type[Any],
        rule: str,
    ) -> None:
        """Install one exact low-level D-Bus signal match.

        Args:
            bus (Any): Connected D-Bus adapter.
            constants (Any): Imported dbus-next constants module.
            message_type (type[Any]): Imported dbus-next Message class.
            rule (str): Complete match rule.

        Returns:
            None
        """
        await cls._call(
            bus,
            constants,
            message_type,
            destination=cls.DBUS_SERVICE,
            path=cls.DBUS_PATH,
            interface=cls.DBUS_INTERFACE,
            member='AddMatch',
            signature='s',
            body=[rule],
        )

    async def _watch_owner(
        self,
        bus: Any,
        constants: Any,
        message_type: type[Any],
        service: str,
    ) -> None:
        """Watch the exact provider generation used during setup.

        Args:
            bus (Any): Connected D-Bus adapter.
            constants (Any): Imported dbus-next constants module.
            message_type (type[Any]): Imported dbus-next Message class.
            service (str): Well-known provider name.

        Returns:
            None
        """
        await self._add_match(
            bus,
            constants,
            message_type,
            "type='signal',sender='org.freedesktop.DBus',"
            "path='/org/freedesktop/DBus',"
            "interface='org.freedesktop.DBus',member='NameOwnerChanged',"
            f"arg0='{service}'",
        )

    async def configure_logind(
        self,
        bus: Any,
        constants: Any,
        message_type: type[Any],
    ) -> bool:
        """Bind logind signals to this process's actual session and owner.

        Args:
            bus (Any): Connected system bus.
            constants (Any): Imported dbus-next constants module.
            message_type (type[Any]): Imported dbus-next Message class.

        Returns:
            bool: Initial ``LockedHint`` for the own session.
        """
        owner = await self._name_owner(bus, constants, message_type, self.LOGIN_SERVICE)
        session_reply = await self._call(
            bus,
            constants,
            message_type,
            destination=self.LOGIN_SERVICE,
            path=self.LOGIN_MANAGER_PATH,
            interface=self.LOGIN_MANAGER_INTERFACE,
            member='GetSessionByPID',
            signature='u',
            body=[os.getpid()],
        )
        if (
            len(session_reply.body) != 1
            or type(session_reply.body[0]) is not str
            or not session_reply.body[0].startswith('/org/freedesktop/login1/session/')
        ):
            raise OSError('Linux lifecycle session identity is invalid')
        session_path: str = session_reply.body[0]
        routes = (
            (self.LOGIN_MANAGER_PATH, self.LOGIN_MANAGER_INTERFACE, 'PrepareForSleep'),
            (session_path, self.LOGIN_SESSION_INTERFACE, 'Lock'),
            (session_path, self.LOGIN_SESSION_INTERFACE, 'Unlock'),
        )
        for path, interface, member in routes:
            await self._add_match(
                bus,
                constants,
                message_type,
                f"type='signal',sender='{owner}',path='{path}',"
                f"interface='{interface}',member='{member}'",
            )
            self._trusted_routes.add((owner, path, interface, member))
        await self._watch_owner(bus, constants, message_type, self.LOGIN_SERVICE)
        if (
            await self._name_owner(bus, constants, message_type, self.LOGIN_SERVICE)
            != owner
        ):
            raise OSError('Linux lifecycle provider changed during setup')
        self._service_owners[self.LOGIN_SERVICE] = owner

        locked_reply = await self._call(
            bus,
            constants,
            message_type,
            destination=self.LOGIN_SERVICE,
            path=session_path,
            interface='org.freedesktop.DBus.Properties',
            member='Get',
            signature='ss',
            body=[self.LOGIN_SESSION_INTERFACE, 'LockedHint'],
        )
        if len(locked_reply.body) != 1:
            raise OSError('Linux lifecycle initial lock state is unavailable')
        locked = getattr(locked_reply.body[0], 'value', None)
        if type(locked) is not bool:
            raise OSError('Linux lifecycle initial lock state is invalid')
        return locked

    async def configure_screen_savers(
        self,
        bus: Any,
        constants: Any,
        message_type: type[Any],
    ) -> int:
        """Register only screen-saver services with a proven current owner.

        Args:
            bus (Any): Connected session bus.
            constants (Any): Imported dbus-next constants module.
            message_type (type[Any]): Imported dbus-next Message class.

        Returns:
            int: Number of validated optional providers.
        """
        configured = 0
        for service, path, interface in self.SCREEN_SAVER_SERVICES:
            try:
                owner = await self._name_owner(bus, constants, message_type, service)
            except OSError:
                continue
            await self._add_match(
                bus,
                constants,
                message_type,
                f"type='signal',sender='{owner}',path='{path}',"
                f"interface='{interface}',member='ActiveChanged'",
            )
            await self._watch_owner(bus, constants, message_type, service)
            if await self._name_owner(bus, constants, message_type, service) != owner:
                raise OSError('Linux lifecycle provider changed during setup')
            self._service_owners[service] = owner
            self._trusted_routes.add((owner, path, interface, 'ActiveChanged'))
            configured += 1
        return configured

    def inspect(self, message: Any) -> LinuxLifecycleSignal | None:
        """Validate message type, provider generation, path, and payload shape.

        Args:
            message (Any): Candidate low-level dbus-next message.

        Returns:
            LinuxLifecycleSignal | None: Validated signal classification, if any.
        """
        if getattr(message, 'message_type', None) != self._signal_message_type:
            return None
        sender = getattr(message, 'sender', None)
        path = getattr(message, 'path', None)
        interface = getattr(message, 'interface', None)
        member = getattr(message, 'member', None)
        body = getattr(message, 'body', None)
        if (
            type(sender) is not str
            or type(path) is not str
            or type(interface) is not str
            or type(member) is not str
        ):
            return None
        if (
            sender == self.DBUS_SERVICE
            and path == self.DBUS_PATH
            and interface == self.DBUS_INTERFACE
            and member == 'NameOwnerChanged'
        ):
            lost = (
                isinstance(body, list)
                and len(body) == 3
                and all(type(value) is str for value in body)
                and self._service_owners.get(body[0]) == body[1]
                and body[2] != body[1]
            )
            return LinuxLifecycleSignal(source_lost=lost) if lost else None
        if (
            sender,
            path,
            interface,
            member,
        ) not in self._trusted_routes or not isinstance(body, list):
            return None
        return LinuxLifecycleSignal(
            source_lost=False,
            interface=interface,
            member=member,
            body=body,
        )
