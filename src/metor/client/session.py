"""High-level endpoint-based reference client for interacting with a Metor daemon."""

import socket
from typing import Callable, Optional, Type, TypeVar

from metor.client.auth import (
    AuthProvider,
    IpcAuthExchange,
    IpcAuthResult,
)
from metor.client.ipc import IpcClient
from metor.core.api import (
    DaemonLockedEvent,
    Delivery,
    InitCommand,
    InitEvent,
    IpcCommand,
    IpcEvent,
    LockCommand,
    ProtocolMismatchEvent,
    RegisterLiveConsumerCommand,
    SendMessageCommand,
    TextContent,
    ensure_request_id,
)
from metor.utils.constants import Constants

T = TypeVar('T', bound=IpcEvent)


def parse_endpoint(endpoint: str | int) -> tuple[str, int]:
    """
    Parses an endpoint definition into host and port.

    Args:
        endpoint (str | int): Formatted as "host:port", "port", or integer port.

    Raises:
        ValueError: If endpoint format is invalid or port is out of range.

    Returns:
        tuple[str, int]: Resolved host and integer port.
    """
    if isinstance(endpoint, int):
        return Constants.LOCALHOST, endpoint

    endpoint_str: str = endpoint.strip()
    if ':' in endpoint_str:
        host, _, port_str = endpoint_str.rpartition(':')
        resolved_host: str = host or Constants.LOCALHOST
        return resolved_host, int(port_str)

    return Constants.LOCALHOST, int(endpoint_str)


class MetorClient:
    """High-level client managing connection, auth, and event streaming with a Metor daemon."""

    def __init__(
        self,
        endpoint: str | int,
        *,
        auth_provider: Optional[AuthProvider] = None,
        on_event: Optional[Callable[[IpcEvent], None]] = None,
        on_disconnect: Optional[Callable[[], None]] = None,
        timeout: float = Constants.DEFAULT_IPC_TIMEOUT,
        client_version: str = '0.2.0',
    ) -> None:
        """
        Initializes one MetorClient.

        Args:
            endpoint (str | int): Daemon endpoint (e.g. "127.0.0.1:50051" or 50051).
            auth_provider (Optional[AuthProvider]): Credential provider for unlock and session auth.
            on_event (Optional[Callable[[IpcEvent], None]]): Callback for incoming async events.
            on_disconnect (Optional[Callable[[], None]]): Callback fired if socket connection drops.
            timeout (float): Socket connect and read timeout.
            client_version (str): Client application version reported in handshake.

        Returns:
            None
        """
        host, port = parse_endpoint(endpoint)
        self._host: str = host
        self._port: int = port
        self._auth_provider: Optional[AuthProvider] = auth_provider
        self._on_event: Callable[[IpcEvent], None] = on_event or (lambda _e: None)
        self._on_disconnect: Callable[[], None] = on_disconnect or (lambda: None)
        self._timeout: float = timeout
        self._client_version: str = client_version

        self._ipc: IpcClient = IpcClient(
            port=self._port,
            timeout=self._timeout,
            on_event=self._handle_async_event,
            on_disconnect=self._handle_disconnect,
            host=self._host,
        )
        self._init_event: Optional[InitEvent] = None

    @property
    def init_event(self) -> Optional[InitEvent]:
        """
        Returns the cached InitEvent after a successful bootstrap.

        Args:
            None

        Returns:
            Optional[InitEvent]: The init event DTO if bootstrapped, else None.
        """
        return self._init_event

    @property
    def is_connected(self) -> bool:
        """
        Returns True if the raw socket is currently open.

        Args:
            None

        Returns:
            bool: True if connected, False otherwise.
        """
        return self._ipc._socket is not None

    def connect(self) -> bool:
        """
        Establishes the raw TCP connection to the daemon endpoint.

        Args:
            None

        Returns:
            bool: True if connection succeeded, False otherwise.
        """
        return self._ipc.connect(start_listener=False)

    def disconnect(self) -> None:
        """
        Closes the active IPC connection and stops background listener threads.

        Args:
            None

        Returns:
            None
        """
        self._ipc.stop()

    def send_command(self, cmd: IpcCommand) -> None:
        """
        Sends one typed IPC command to the daemon.

        Args:
            cmd (IpcCommand): The command payload to send.

        Returns:
            None
        """
        self._ipc.send_command(cmd)

    def send_text(
        self, target: str, delivery: Delivery, text: str, msg_id: str
    ) -> None:
        """Sends text through the typed public message boundary.

        Args:
            target (str): Destination alias or onion.
            delivery (Delivery): Requested delivery semantics.
            text (str): UTF-8 text payload.
            msg_id (str): Stable logical message identifier.

        Returns:
            None
        """
        self.send_command(
            SendMessageCommand(
                target=target,
                delivery=delivery,
                content=TextContent(text),
                msg_id=msg_id,
            )
        )

    def lock(self) -> bool:
        """Securely locks the daemon while retaining the IPC connection.

        Args:
            None

        Returns:
            bool: True after the daemon confirms the locked state.
        """
        return self.request(LockCommand(), DaemonLockedEvent) is not None

    def request(
        self,
        cmd: IpcCommand,
        expected_type: Type[T],
    ) -> Optional[T]:
        """
        Executes a synchronous request/response exchange on the socket, handling auth gates.

        Args:
            cmd (IpcCommand): Outgoing request command.
            expected_type (Type[T]): Expected response event DTO class.

        Returns:
            Optional[T]: Decoded response event, or None if the request failed or was rejected.
        """
        request_id: str = ensure_request_id(cmd)
        self._ipc.send_command(cmd)

        auth_exchange: IpcAuthExchange = self._create_auth_exchange(request_id)

        while True:
            try:
                event: Optional[IpcEvent] = self._ipc.read_event()
            except (socket.timeout, OSError, ValueError):
                return None

            if event is None:
                return None

            if event.request_id is not None and event.request_id != request_id:
                continue

            auth_result: IpcAuthResult = auth_exchange.handle(event)
            if auth_result.handled:
                if auth_result.resend_original_command:
                    self._ipc.send_command(cmd)
                    continue

                if auth_result.auth_incomplete or auth_result.error_event is not None:
                    return None

                continue

            if isinstance(event, expected_type):
                return event

            if isinstance(event, ProtocolMismatchEvent):
                return None

    def bootstrap(self) -> Optional[InitEvent]:
        """
        Executes the canonical bootstrap handshake including unlock and session auth.

        Args:
            None

        Returns:
            Optional[InitEvent]: Handshake response event, or None on failure.
        """
        if not self.is_connected:
            if not self.connect():
                return None

        init_cmd: InitCommand = InitCommand(
            protocol_version=Constants.IPC_PROTOCOL_VERSION,
        )
        init_event: Optional[InitEvent] = self.request(init_cmd, InitEvent)
        if init_event is not None:
            self._init_event = init_event
        return init_event

    def register_live_consumer(self) -> bool:
        """
        Registers this client as a live consumer and starts background event processing.

        Args:
            None

        Returns:
            bool: True if listener started and registration was sent.
        """
        if not self.is_connected:
            return False

        self._ipc.start_listener()
        self._ipc.send_command(RegisterLiveConsumerCommand())
        return True

    def _create_auth_exchange(self, request_id: str) -> IpcAuthExchange:
        """
        Creates an IpcAuthExchange configured with the active auth provider.

        Args:
            request_id (str): The stable request correlation identifier.

        Returns:
            IpcAuthExchange: The prepared auth-gate state machine.
        """

        def _prompt_session(challenge: str, salt: str) -> Optional[str]:
            """
            Derives session proof via the configured auth provider.

            Args:
                challenge (str): The challenge issued by daemon.
                salt (str): The salt issued by daemon.

            Returns:
                Optional[str]: Derived HMAC proof or None.
            """
            if self._auth_provider is None:
                return None
            return self._auth_provider.get_session_auth_proof(challenge, salt)

        def _prompt_unlock() -> Optional[str]:
            """
            Retrieves unlock password via the configured auth provider.

            Args:
                None

            Returns:
                Optional[str]: Master password or None.
            """
            if self._auth_provider is None:
                return None
            return self._auth_provider.get_unlock_password()

        return IpcAuthExchange(
            prompt_session_proof=_prompt_session,
            prompt_unlock_password=_prompt_unlock,
            send_command=self._ipc.send_command,
            request_id=request_id,
        )

    def _handle_async_event(self, event: IpcEvent) -> None:
        """
        Dispatches incoming async events to the user-supplied handler.

        Args:
            event (IpcEvent): The incoming IPC event.

        Returns:
            None
        """
        self._on_event(event)

    def _handle_disconnect(self) -> None:
        """
        Handles unexpected daemon disconnects.

        Args:
            None

        Returns:
            None
        """
        self._on_disconnect()
