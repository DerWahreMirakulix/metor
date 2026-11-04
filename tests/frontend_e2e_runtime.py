"""Actual encrypted Core/IPC fixtures with controlled loopback peer routing.

The sole substituted production dependency is the Tor process and SOCKS route.
Peer framing, signatures, DROP workers, LIVE and Call state, SQLCipher, local
authorization, and frontend host discovery remain production implementations.
"""

import atexit
import base64
from collections.abc import Callable
from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import threading
from typing import Optional
from unittest.mock import patch

from metor.application.frontend import create_local_frontend_host
from metor.client import FrontendHost, MetorClient, build_session_auth_proof
from metor.core.api import EventType, IpcEvent, JsonValue
from metor.core.daemon.managed import DaemonStatus, create_managed_daemon
from metor.core.daemon.managed.engine import Daemon
from metor.core.key import KeyManager
from metor.core.tor import TorManager
from metor.data.profile import ProfileManager
from metor.utils import Constants


FIXTURE_PASSWORD: str = 'disposable-frontend-e2e-password'
FIXTURE_WAIT_SECONDS: float = Constants.DEFAULT_IPC_TIMEOUT


class FixtureAuthProvider:
    """Supplies only the disposable credential through the public SDK protocol."""

    def get_unlock_password(self) -> str:
        """Return the temporary profile credential without a stream prompt."""
        return FIXTURE_PASSWORD

    def get_session_auth_proof(self, challenge: str, salt: str) -> str:
        """Authenticate each connection with the actual one-use challenge proof."""
        return build_session_auth_proof(FIXTURE_PASSWORD, challenge, salt)


class LoopbackPeerTor(TorManager):
    """Route authenticated production peer traffic to bounded local TCP listeners."""

    def __init__(
        self,
        profile: ProfileManager,
        key_manager: KeyManager,
        routes: dict[str, 'LoopbackPeerTor'],
    ) -> None:
        """Generate actual signing keys while keeping Tor absent from the fixture."""
        super().__init__(profile, key_manager)
        key_manager.generate_keys()
        public_key = key_manager.get_metor_key()[32:]
        version = bytes([3])
        checksum = hashlib.sha3_256(b'.onion checksum' + public_key + version).digest()[
            :2
        ]
        self.onion = base64.b32encode(public_key + checksum + version).decode().lower()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
            reservation.bind((Constants.LOCALHOST, 0))
            self.incoming_port = int(reservation.getsockname()[1])
        self._routes = routes
        self._fixture_running = False
        routes[self.onion] = self

    def start(self) -> tuple[bool, Optional[EventType], dict[str, JsonValue]]:
        """Expose the local route without launching any external process."""
        self._fixture_running = True
        return True, None, {}

    def stop(self) -> None:
        """Revoke new local routes while Core releases its actual peer sockets."""
        self._fixture_running = False

    def is_running(self) -> bool:
        """Report the explicit controlled adapter lifetime to Core."""
        return self._fixture_running

    def connect(self, onion: str) -> socket.socket:  # type: ignore[override]
        """Open an actual bounded TCP connection to a known fixture peer only."""
        destination = self._routes.get(onion.removesuffix('.onion'))
        if destination is None or not destination.is_running():
            raise ConnectionRefusedError('No controlled fixture peer route')
        assert destination.incoming_port is not None
        return socket.create_connection(
            (Constants.LOCALHOST, destination.incoming_port),
            timeout=FIXTURE_WAIT_SECONDS,
        )

    def rotate_circuits(
        self,
    ) -> tuple[bool, Optional[EventType], dict[str, JsonValue]]:
        """Retain the same explicit loopback route for retunnel lifecycle checks."""
        return True, None, {}


class CoreEndpoint:
    """Own one actual managed daemon and its separately authenticated SDK clients."""

    def __init__(
        self,
        owner: 'EncryptedFrontendRuntime',
        profile_name: str,
        routes: dict[str, LoopbackPeerTor],
    ) -> None:
        """Create protected persistence through the public profile/factory boundaries."""
        self._owner = owner
        self.profile_name = profile_name
        self.endpoint_profile_name = f'{profile_name}-endpoint'
        self.password = FIXTURE_PASSWORD
        self.profile_manager = ProfileManager(profile_name)
        created = ProfileManager.add_profile_folder(
            profile_name, master_password=FIXTURE_PASSWORD
        )
        if not created.success:
            raise AssertionError('Disposable encrypted profile creation failed')
        self._ready = threading.Event()
        self._run_errors: list[BaseException] = []

        def transport(profile: ProfileManager, key: KeyManager) -> LoopbackPeerTor:
            """Substitute only the process/routing adapter at the factory boundary."""
            self.tor = LoopbackPeerTor(profile, key, routes)
            return self.tor

        def status(
            event: EventType | DaemonStatus, _parameters: dict[str, JsonValue]
        ) -> None:
            """Wait for the production runtime's committed readiness milestone."""
            if event == DaemonStatus.ACTIVE:
                self._ready.set()

        with (
            patch('metor.core.daemon.managed.bootstrap.TorManager', transport),
            patch('metor.core.daemon.managed.engine.daemon.signal.signal'),
        ):
            self.daemon: Daemon = create_managed_daemon(
                self.profile_manager,
                password=FIXTURE_PASSWORD,
                status_callback=status,
            )
        atexit.unregister(self.daemon.stop)
        owner._stack.callback(self.close)

        def run() -> None:
            """Record startup failure without leaking private exception values."""
            try:
                self.daemon.run()
            except BaseException as error:
                self._run_errors.append(error)
                self._ready.set()

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        if not self._ready.wait(FIXTURE_WAIT_SECONDS) or self._run_errors:
            raise AssertionError('Actual fixture daemon did not become ready')
        port = self.daemon._ipc.port
        onion = self.tor.onion
        if port is None or onion is None:
            raise AssertionError('Actual fixture Core endpoint is absent')
        self.port = port
        self.onion = onion
        # The fixture does not impersonate a separately managed daemon process.
        # PID-free discovery is the public local endpoint format; subprocess
        # frontends also exercise a real explicitly forwarded profile below.
        self.profile_manager.paths.get_daemon_pid_file().unlink(missing_ok=True)
        forwarded = ProfileManager.add_profile_folder(
            self.endpoint_profile_name, is_remote=True, port=self.port
        )
        if not forwarded.success:
            raise AssertionError('Disposable forwarded endpoint creation failed')

    def client(
        self,
        *,
        live_consumer: bool = False,
        on_event: Callable[[IpcEvent], None] | None = None,
    ) -> MetorClient:
        """Open and authorize an actual public SDK session on the real IPC server."""
        client = MetorClient(
            self.port,
            auth_provider=FixtureAuthProvider(),
            timeout=FIXTURE_WAIT_SECONDS,
            on_event=on_event,
        )
        self._owner._stack.callback(client.disconnect)
        if client.bootstrap() is None:
            raise AssertionError('Actual fixture client authorization failed')
        if live_consumer and not client.register_live_consumer():
            raise AssertionError('Actual fixture live-consumer registration failed')
        return client

    def frontend_host(self) -> FrontendHost:
        """Create the production local host for native encrypted-profile startup."""
        return create_local_frontend_host(self.profile_manager, False)

    def close(self) -> None:
        """Stop actual workers and require bounded owning thread cleanup."""
        self.daemon.stop()
        self._thread.join(FIXTURE_WAIT_SECONDS)
        if self._thread.is_alive():
            raise AssertionError('Actual fixture daemon worker did not stop')
        if self._run_errors:
            raise AssertionError('Actual fixture daemon lifetime failed')


class EncryptedFrontendRuntime(CoreEndpoint):
    """Share one protected runtime and an optional peer across actual frontends."""

    def __init__(self, *, paired: bool = True) -> None:
        """Defer all temporary resource mutation to explicit context entry."""
        self._paired = paired
        self._stack = ExitStack()
        self.peer: CoreEndpoint | None = None

    def __enter__(self) -> 'EncryptedFrontendRuntime':
        """Start real protected Core workers with isolated host configuration."""
        try:
            temporary = self._stack.enter_context(
                TemporaryDirectory(prefix='metor-frontend-e2e-')
            )
            self.data_parent = Path(temporary)
            self.data_root = self.data_parent / '.metor'
            self._stack.enter_context(patch.object(Constants, 'DATA', self.data_root))
            self._stack.enter_context(
                patch.dict(
                    os.environ,
                    {'METOR_DATA_DIR_PARENT': str(self.data_parent)},
                )
            )
            self._stack.enter_context(
                patch('metor.core.daemon.managed.engine.daemon.signal.signal')
            )
            routes: dict[str, LoopbackPeerTor] = {}
            CoreEndpoint.__init__(self, self, 'frontend-e2e', routes)
            if self._paired:
                self.peer = CoreEndpoint(self, 'frontend-e2e-peer', routes)
            return self
        except BaseException:
            self._stack.close()
            raise

    def __exit__(
        self,
        _kind: type[BaseException] | None,
        _error: BaseException | None,
        _traceback: object,
    ) -> None:
        """Release SDK connections, workers, keys and temporary profiles in order."""
        self._stack.close()

    def environment(self) -> dict[str, str]:
        """Return actual subprocess configuration without changing inherited HOME."""
        return {
            **os.environ,
            'METOR_DATA_DIR_PARENT': str(self.data_parent),
        }
