"""Dedicated CALL transports reject message bytes without creating LIVE authority."""

import socket
import threading
import unittest
from unittest.mock import Mock

from metor.core.api import CallReason, CallState
from metor.core.daemon.managed.models import TorCommand
from metor.core.daemon.managed.network.calls import CallController
from metor.core.daemon.managed.network.state import StateTracker
from metor.core.daemon.managed.network.stream import TcpStreamReader
from metor.shared import Constants


class CallTransportBoundaryTests(unittest.TestCase):
    """Uses actual bounded stream parsing and socket retirement after authentication."""

    def test_call_only_socket_cannot_admit_live_text_drop_or_voice(self) -> None:
        """Wrong-domain payload closes only CALL and never produces chat permission."""
        for payload in (
            f'{TorCommand.MSG.value} message payload\n'.encode(),
            f'{TorCommand.DROP.value} message payload\n'.encode(),
            f'{TorCommand.VOICE_BEGIN.value} voice opus\n'.encode(),
            f'{TorCommand.DROP_VOICE_BEGIN.value} voice opus\n'.encode(),
        ):
            with self.subTest(command=payload.split()[0]):
                local, remote = socket.socketpair()
                state = StateTracker()
                contacts = Mock()
                contacts.ensure_alias_for_onion.return_value = 'Peer'
                stopped = threading.Event()
                calls = CallController(
                    Mock(), contacts, Mock(), state, lambda _event: None, stopped
                )
                try:
                    local.settimeout(Constants.CALL_KEEPALIVE_SEC)
                    remote.settimeout(Constants.DEFAULT_IPC_TIMEOUT)
                    remote.sendall(
                        f'{TorCommand.CALL_OFFER.value} wire-call {Constants.CALL_CODEC} 0\n'.encode()
                        + payload
                    )
                    calls.accept_transport('peer', local, TcpStreamReader(local))
                    self.assertEqual(state.get_active_onions(), [])
                    self.assertIsNone(state.get_connection('peer'))
                    self.assertEqual(len(calls.sessions), 1)
                    session = next(iter(calls.sessions.values()))
                    self.assertIs(session.info.state, CallState.ENDED)
                    self.assertIs(session.info.reason, CallReason.TRANSPORT_LOST)
                    self.assertIsNone(session.owner)
                    self.assertFalse(session.frames)
                    self.assertEqual(remote.recv(Constants.CALL_MAX_FRAME_BYTES), b'')
                finally:
                    calls.close()
                    stopped.set()
                    calls.monitor.join(Constants.DEFAULT_IPC_TIMEOUT)
                    state.abort_all_sockets()
                    local.close()
                    remote.close()
                    self.assertFalse(calls.monitor.is_alive())
