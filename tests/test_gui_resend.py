"""Delivered-own-LIVE resend through real protected Core IPC and finite volatile sources."""

import base64
from dataclasses import replace
import unittest
from unittest.mock import Mock, patch

import test_gui_producers as support
from metor.client import FrontendLaunchContext
from metor.core.api import (
    Delivery,
    MessageDirectionCode,
    MessageStatusCode,
    RuntimeSnapshotEvent,
)
from metor.data import MessageDirection
from metor.shared import Constants
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.platform.audio import PcmVoice
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.runtime.resend.source import available_source
from metor.ui.gui.runtime.transcript import TranscriptItem
from metor.ui.gui.state.media import PlaybackTarget


_GUI_OPERATION_TIMEOUT_SEC: float = Constants.DEFAULT_IPC_TIMEOUT


class ResendCoreTests(unittest.TestCase):
    """Uses encrypted temporary profiles; no peer, microphone, or owner profile is touched."""

    def setUp(self) -> None:
        """Attaches an authorized GUI to the isolated producer test runtime.

        Args:
            None
        Returns:
            None
        """
        self.h = support.GuiProducerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.gui = GuiController(FrontendLaunchContext('voice-owned', Mock()))
        self.addCleanup(self.gui.close)
        self.gui.client = self.h.client
        self.gui.state.snapshot = self.h.client.runtime_snapshot()
        self.gui.state.capabilities = frozenset(self.h.client.init_event.capabilities)
        self.gui.state.covered = False
        self.gui.voice_owner.token = self.h.owner
        self.payload = b'\x01\x00' * 960

    def source(self, *, voice: bool = False) -> PlaybackTarget:
        """Retains a synthetic already-delivered source after its Core copy is absent.

        Args:
            voice: Whether the permitted retained source is PCM instead of text.
        Returns:
            PlaybackTarget: Original source, distinct from any created DROP.
        """
        item = TranscriptItem(
            self.h.onion,
            Delivery.LIVE,
            MessageDirectionCode.OUT,
            'original-live',
            None if voice else 'Exact retained text',
            status=MessageStatusCode.DELIVERED,
            finalized=True,
            codec=PcmVoice.CODEC if voice else None,
            size_bytes=len(self.payload) if voice else 0,
        )
        self.assertTrue(self.gui.transcript.admit(item))
        target = self.gui.playback.target(
            self.h.onion,
            Delivery.LIVE,
            MessageDirectionCode.OUT,
            item.msg_id,
        )
        self.assertIsNotNone(target)
        if voice:
            self.assertTrue(
                self.gui.playback.cache.append(target, 0, self.payload, complete=True)
            )
        return target

    def settle(self) -> None:
        """Drains actual GUI operations and bounded scheduled receipt readbacks.

        Args:
            None
        Returns:
            None
        """
        for _ in range(12):
            if self.gui._worker is not None:
                self.gui._worker.join(_GUI_OPERATION_TIMEOUT_SEC)
                self.assertFalse(
                    self.gui._worker.is_alive(),
                    (
                        'GUI operation exceeded its normal IPC bound: '
                        f'{_GUI_OPERATION_TIMEOUT_SEC}s'
                    ),
                )
            self.gui.poll()
            if not self.gui.state.busy and not self.gui.resend.pending:
                break
        self.assertFalse(self.gui.resend.pending)

    def test_text_creates_distinct_drop_without_changing_original(self) -> None:
        """The new DROP is durable while the original delivered LIVE presentation stays intact.

        Args:
            None
        Returns:
            None
        """
        target = self.source()
        self.assertTrue(self.gui.resend.start(target.peer, target.msg_id))
        identity = self.gui.resend.current.msg_id
        self.assertNotEqual(identity, target.msg_id)
        self.settle()
        self.assertEqual(self.gui.resend.state, 'queued')
        records = self.h.messages.get_chat_history(self.h.onion)
        self.assertEqual([item.msg_id for item in records], [identity])
        self.assertIn('Exact retained text', records[0].payload)
        self.assertEqual(
            next(iter(self.gui.transcript.items.values())).delivery, Delivery.LIVE
        )
        self.assertEqual(
            next(iter(self.gui.transcript.items.values())).status,
            MessageStatusCode.DELIVERED,
        )

    def test_voice_unknown_commit_reads_new_id_without_repeating_commit(self) -> None:
        """A lost actual positive commit is resolved by receipt, preserving exact encoded bytes.

        Args:
            None
        Returns:
            None
        """
        target = self.source(voice=True)
        commit = self.h.client.commit_voice

        def lost(*args: object, **kwargs: object) -> None:
            """Drops only the real response after Core committed the new copy.

            Args:
                args: Original public call arguments.
                kwargs: Original exact-owner arguments.
            Returns:
                None
            """
            commit(*args, **kwargs)
            raise TimeoutError('injected lost commit response')

        with patch.object(self.h.client, 'commit_voice', side_effect=lost) as observed:
            self.assertTrue(self.gui.resend.start(target.peer, target.msg_id))
            identity = self.gui.resend.current.msg_id
            self.assertFalse(self.gui.resend.start(target.peer, target.msg_id))
            self.settle()
            self.assertEqual(observed.call_count, 1)
        self.assertEqual(self.gui.resend.state, 'queued')
        self.assertNotEqual(identity, target.msg_id)
        event = self.h.other.get_voice_chunk(
            target.peer,
            identity,
            MessageDirectionCode.OUT,
            0,
            Constants.VOICE_CHUNK_MAX_BYTES,
        )
        self.assertEqual(base64.b64decode(event.data), self.payload)
        self.assertTrue(event.complete)
        self.assertEqual(
            self.gui.playback.cache.complete_size(target), len(self.payload)
        )

    def test_unknown_append_keeps_new_copy_unsent_until_explicit_discard(self) -> None:
        """Accepted bytes with a lost result never trigger another append, finalize, or commit.

        Args:
            None
        Returns:
            None
        """
        target = self.source(voice=True)
        append = self.h.client.append_voice

        def lost(*args: object, **kwargs: object) -> None:
            """Drops an actual accepted append acknowledgement.

            Args:
                args: Original encoded upload arguments.
                kwargs: Exact owner token.
            Returns:
                None
            """
            append(*args, **kwargs)
            raise TimeoutError('injected lost append response')

        with (
            patch.object(self.h.client, 'append_voice', side_effect=lost) as observed,
            patch.object(
                self.h.client, 'commit_voice', wraps=self.h.client.commit_voice
            ) as commit,
        ):
            self.assertTrue(self.gui.resend.start(target.peer, target.msg_id))
            identity = self.gui.resend.current.msg_id
            self.settle()
            self.assertEqual(observed.call_count, 1)
            commit.assert_not_called()
        self.assertEqual(self.gui.resend.state, 'draft')
        self.assertFalse(self.gui.resend.start(target.peer, target.msg_id))
        self.assertEqual(self.h.messages.get_chat_history(target.peer), [])
        self.assertTrue(self.gui.resend.discard())
        self.settle()
        self.assertEqual(self.gui.resend.state, 'discarded')
        self.assertIsNone(
            self.h.messages.get_voice_payload(
                target.peer, identity, MessageDirection.OUT
            )
        )
        self.assertTrue(self.gui.resend.available(target.peer, target.msg_id))


class ResendSourceTests(unittest.TestCase):
    """Checks absent, partial, revoked and leased sources without public service IO."""

    def setUp(self) -> None:
        """Creates one inert current-runtime source cache.

        Args:
            None
        Returns:
            None
        """
        self.gui = GuiController(FrontendLaunchContext('fixture', Mock()))
        self.addCleanup(self.gui.close)
        self.gui.state.covered = False
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture', '', epoch='epoch', profile_instance_id='instance'
        )
        self.target = self.gui.playback.target(
            'peer', Delivery.LIVE, MessageDirectionCode.OUT, 'source'
        )
        self.cache = self.gui.playback.cache

    def test_only_complete_own_delivered_source_is_eligible(self) -> None:
        """Received, pending, partial, evicted, locked and simulated sources cannot be resent.

        Args:
            None
        Returns:
            None
        """
        item = TranscriptItem(
            'peer',
            Delivery.LIVE,
            MessageDirectionCode.IN,
            'source',
            codec=PcmVoice.CODEC,
            size_bytes=4,
            finalized=True,
            status=MessageStatusCode.READ,
        )
        self.gui.transcript.admit(item)
        self.cache.append(self.target, 0, b'\x00' * 4, complete=True)
        self.assertIsNone(available_source(self.gui, 'peer', 'source'))
        self.gui.transcript.admit(
            replace(
                item,
                direction=MessageDirectionCode.OUT,
                status=MessageStatusCode.PENDING,
            )
        )
        self.assertIsNone(available_source(self.gui, 'peer', 'source'))
        self.gui.transcript.admit(replace(item, direction=MessageDirectionCode.OUT))
        self.assertIsNotNone(available_source(self.gui, 'peer', 'source'))
        self.gui.simulator = True
        self.assertFalse(self.gui.resend.available('peer', 'source'))
        self.gui.client = Mock()
        self.assertFalse(self.gui.resend.start('peer', 'source'))
        self.gui.client.request.assert_not_called()
        self.gui.client = None
        self.gui.state.covered = True
        self.assertIsNone(available_source(self.gui, 'peer', 'source'))
        self.gui.state.covered = False
        self.cache.discard(self.target)
        self.assertIsNone(available_source(self.gui, 'peer', 'source'))
        self.assertFalse(self.cache.append(self.target, 0, b'\x00' * 4, complete=True))

    def test_leases_prevent_eviction_but_privacy_clear_revokes_them(self) -> None:
        """Concurrent replay/resend pins bounded bytes; lock still destroys their references.

        Args:
            None
        Returns:
            None
        """
        other = replace(self.target, msg_id='other')
        with patch.object(GuiLimits, 'MEDIA_CACHE_BYTES', 4):
            self.assertTrue(self.cache.append(self.target, 0, b'0000', complete=True))
            with self.cache.retain(self.target) as first:
                with self.cache.retain(self.target) as second:
                    self.assertTrue(first and second)
                    self.assertFalse(
                        self.cache.append(other, 0, b'1111', complete=True)
                    )
                self.assertFalse(self.cache.append(other, 0, b'1111', complete=True))
            self.assertTrue(self.cache.append(other, 0, b'1111', complete=True))
            self.assertIsNone(self.cache.complete_size(self.target))
            with self.cache.retain(other) as retained:
                self.assertTrue(retained)
                self.cache.clear()
                self.assertIsNone(self.cache.read(other, 0, 4))
            self.assertFalse(self.cache.append(other, 0, b'1111', complete=True))

    def test_missing_capture_range_never_becomes_a_complete_source(self) -> None:
        """Finalization cannot manufacture a lost range or mutate an already complete recording.

        Args:
            None
        Returns:
            None
        """
        self.cache.append(self.target, 0, b'00', complete=False)
        self.assertFalse(self.cache.mark_complete(self.target, 4))
        self.assertIsNone(self.cache.read(self.target, 0, 4))
        self.assertFalse(self.cache.append(self.target, 4, b'11', complete=False))
        self.assertFalse(self.cache.mark_complete(self.target, 6))
        self.cache.append(self.target, 0, b'0011', complete=True)
        self.assertFalse(self.cache.append(self.target, 4, b'22', complete=True))
        self.assertEqual(self.cache.read(self.target, 0, 6), (b'0011', 4))


if __name__ == '__main__':
    unittest.main()
