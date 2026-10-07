"""Actual cross-frontend text delivery and text-only media capability boundaries."""

import base64
from collections.abc import Callable
import os
import subprocess
import sys
import time
import unittest

from frontend_e2e_runtime import EncryptedFrontendRuntime, FIXTURE_WAIT_SECONDS
from frontend_gui_terminal import GuiTerminalPeer
from metor.core.api import (
    AddContactCommand,
    CallReason,
    CallState,
    CallStateEvent,
    ContactAddedEvent,
    Delivery,
    GetMessagesCommand,
    MessageDirectionCode,
    MessagesDataEvent,
    MessageStatusCode,
    RegisterVoiceOwnerCommand,
    TextContent,
    VoiceChunkAcceptedEvent,
    VoiceCommittedEvent,
    VoiceDataEvent,
    VoiceFinalizedEvent,
    VoiceOwnerRegisteredEvent,
    VoiceStartedEvent,
)
from metor.shared import Constants
from terminal_pty import PTY_POLL_SECONDS


_VOICE_CODEC: str = 'pcm_s16le_16000_mono'
_PCM_BYTES: bytes = b'\x12\x34' * (Constants.CALL_FRAME_BYTES // 2)


@unittest.skipUnless(os.name == 'posix', 'Actual Terminal peer requires a POSIX PTY')
class FrontendInteropTests(unittest.TestCase):
    """Run independent frontends against two protected production Core runtimes."""

    def setUp(self) -> None:
        """Create an actual CLI-side Core and a separately authenticated Terminal peer."""
        self.runtime = self.enterContext(EncryptedFrontendRuntime())
        assert self.runtime.peer is not None
        self.sender = self.runtime.client(live_consumer=True)
        self.receiver = self.runtime.peer.client()
        self.terminal = GuiTerminalPeer(self.runtime)
        self.addCleanup(self.terminal.close)
        self.terminal.start()

    def _wait(self, predicate: Callable[[], bool], description: str) -> None:
        """Observe real typed outcomes while draining the bounded Terminal output."""
        deadline = time.monotonic() + FIXTURE_WAIT_SECONDS
        assert self.terminal.child is not None
        while time.monotonic() < deadline:
            self.terminal.child.poll_output()
            if predicate():
                return
            time.sleep(PTY_POLL_SECONDS)
        self.fail(description)

    def _cli(self, *arguments: str, peer: bool = False) -> str:
        """Invoke the ordinary Base CLI from outside the repository checkout."""
        endpoint = self.runtime.peer if peer else self.runtime
        assert endpoint is not None
        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'metor',
                '-p',
                endpoint.endpoint_profile_name,
                *arguments,
            ],
            cwd=self.runtime.data_parent,
            env=self.runtime.environment(),
            input=endpoint.password + '\n',
            text=True,
            capture_output=True,
            timeout=FIXTURE_WAIT_SECONDS,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('Traceback', result.stdout + result.stderr)
        self.assertNotIn(endpoint.password, result.stdout + result.stderr)
        return result.stdout

    def _assert_no_live(self) -> None:
        """Text DROP, media notices and call signaling never authorize LIVE chat."""
        for client in (self.sender, self.receiver):
            snapshot = client.runtime_snapshot()
            assert snapshot is not None
            self.assertEqual(snapshot.live_contexts, [])
            self.assertEqual(snapshot.pending, [])
        assert self.terminal.child is not None
        self.terminal.child.poll_output()
        self.assertNotIn('Unknown code:', self.terminal.child.plain_output)

    def test_cli_terminal_drop_roundtrip_without_live(self) -> None:
        """Actual CLI sends arrive in Terminal; Terminal replies appear in CLI inbox."""
        assert self.runtime.peer is not None
        target = self.runtime.peer.onion
        first = 'CLI to Terminal: Grüße — mixed CASE'
        self._cli('send', target, '--', first)
        self.terminal.wait_text(first)
        incoming = self.receiver.request(
            GetMessagesCommand(self.runtime.onion), MessagesDataEvent
        )
        assert incoming is not None
        rows = [
            row
            for row in incoming.messages
            if isinstance(row.content, TextContent) and row.content.text == first
        ]
        self.assertEqual(len(rows), 1)
        self.assertIs(rows[0].direction, MessageDirectionCode.IN)
        self.assertIs(rows[0].delivery, Delivery.DROP)
        reply = 'Terminal reply read by the Base CLI'
        self.terminal.send_drop(reply)

        def reply_arrived() -> bool:
            """Await durable peer delivery before the explicit CLI consumption action."""
            result = self.sender.request(GetMessagesCommand(target), MessagesDataEvent)
            assert result is not None
            return any(
                isinstance(row.content, TextContent) and row.content.text == reply
                for row in result.messages
            )

        self._wait(reply_arrived, 'The actual Terminal reply never reached CLI Core.')
        self.assertIn(reply, self._cli('inbox', target))
        read = self.sender.request(GetMessagesCommand(target), MessagesDataEvent)
        assert read is not None
        consumed = [
            row
            for row in read.messages
            if row.direction is MessageDirectionCode.IN
            and isinstance(row.content, TextContent)
            and row.content.text == reply
        ]
        self.assertEqual(len(consumed), 1)
        self.assertIs(consumed[0].status, MessageStatusCode.READ)
        self._assert_no_live()

    def test_terminal_preserves_voice_and_refuses_call_acceptance(self) -> None:
        """Text-only viewing keeps Voice unread and never creates a silent accepted call."""
        assert self.runtime.peer is not None
        assert self.terminal.child is not None
        child = self.terminal.child
        self.sender.request(
            AddContactCommand('TerminalPeer', self.runtime.peer.onion),
            ContactAddedEvent,
        )
        owner = self.sender.request(
            RegisterVoiceOwnerCommand(), VoiceOwnerRegisteredEvent
        )
        assert owner is not None
        voice_id = 'terminal-retained-voice'
        self.assertIsInstance(
            self.sender.begin_voice(
                self.runtime.peer.onion,
                Delivery.DROP,
                voice_id,
                _VOICE_CODEC,
                owner_token=owner.owner_token,
            ),
            VoiceStartedEvent,
        )
        self.assertIsInstance(
            self.sender.append_voice(
                voice_id,
                0,
                base64.b64encode(_PCM_BYTES).decode(),
                owner_token=owner.owner_token,
            ),
            VoiceChunkAcceptedEvent,
        )
        self.assertIsInstance(
            self.sender.finalize_voice(voice_id, owner_token=owner.owner_token),
            VoiceFinalizedEvent,
        )
        self.assertIsInstance(
            self.sender.commit_voice(
                self.runtime.peer.onion, voice_id, owner_token=owner.owner_token
            ),
            VoiceCommittedEvent,
        )
        self.terminal.wait_text('Playback is not supported in this frontend.')
        self._cli('inbox', self.runtime.onion, peer=True)
        child.line('/inbox GuiCounterpart')
        marker = child.line('/calls')
        child.wait_text('No telephone calls.', after=marker)
        inventory = self.receiver.list_retained_messages(
            target=self.runtime.onion,
            direction=MessageDirectionCode.IN,
            msg_id=voice_id,
        )
        assert inventory is not None
        self.assertEqual(len(inventory.messages), 1)
        self.assertIs(inventory.messages[0].status, MessageStatusCode.UNREAD)
        media = self.receiver.get_voice_chunk(
            self.runtime.onion, voice_id, MessageDirectionCode.IN, 0, len(_PCM_BYTES)
        )
        self.assertIsInstance(media, VoiceDataEvent)
        assert isinstance(media, VoiceDataEvent)
        self.assertEqual(base64.b64decode(media.data), _PCM_BYTES)
        self.assertIsInstance(
            self.sender.start_call(self.runtime.peer.onion, 'terminal-call-offer'),
            CallStateEvent,
        )
        child.wait_text('Accept in a frontend with a local duplex audio adapter.')
        calls = self.receiver.get_calls()
        assert calls is not None
        incoming = [call for call in calls.calls if call.state is CallState.INCOMING]
        self.assertEqual(len(incoming), 1)
        call_id = incoming[0].call_id
        marker = child.line(f'/call accept {call_id}')
        child.wait_text('Terminal cannot start or accept call audio', after=marker)
        calls = self.receiver.get_calls()
        assert calls is not None
        current = next(call for call in calls.calls if call.call_id == call_id)
        self.assertIs(current.state, CallState.INCOMING)
        self.assertFalse(current.owned)
        marker = child.line(f'/call reject {call_id}')
        child.wait_text(f'Call {call_id}: ended (rejected)', after=marker)

        def declined() -> bool:
            """The originating capable client receives the exact explicit refusal."""
            result = self.sender.get_calls()
            assert result is not None
            return any(
                call.call_id == 'terminal-call-offer'
                and call.state is CallState.ENDED
                and call.reason is CallReason.REJECTED
                for call in result.calls
            )

        self._wait(
            declined, 'The real peer did not receive the Terminal call rejection.'
        )
        self._assert_no_live()


if __name__ == '__main__':
    unittest.main()
