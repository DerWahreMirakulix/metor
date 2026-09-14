"""Measured Voice playback card with independent audio-position controls."""

from collections.abc import Callable

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from metor.ui.gui.platform.audio import PcmVoice
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state.media import PlaybackTarget

# Local Package Imports
from .controls import Action, Label, Panel
from .symbol import IconAction, Symbol


class VoiceCard(Panel):
    """Keeps Play, duration/status and Go live in separate nonoverlapping columns."""

    def __init__(
        self,
        controller: GuiController,
        target: PlaybackTarget,
        refresh: Callable[[], None],
        context: Callable[[], object] | None = None,
    ) -> None:
        """Builds one stable Voice message control from its exact source identity.

        Args:
            controller: Public-service GUI coordinator.
            target: Immutable source identity captured by this card.
            refresh: Coalesced repaint request.
            context: Optional exact-item More action.
        Returns:
            None
        """
        super().__init__(
            orientation='horizontal', padding=dp(16), spacing=dp(12), size_hint_y=None
        )
        self.controller, self.target, self.refresh = controller, target, refresh
        self._available = 0
        self._finalized = False
        self.play = IconAction('play', 'Play voice message', self._play)
        self._playing = False
        self.add_widget(self.play)
        self.body = BoxLayout(orientation='vertical', spacing=dp(4), size_hint_y=None)
        self.title = Label('Voice message', role='support')
        self.metadata = Label('', role='caption', tone='textSecondary')
        self.body.add_widget(self.title)
        self.body.add_widget(self.metadata)
        self.body.bind(minimum_height=self.body.setter('height'), height=self._measure)
        self.add_widget(self.body)
        if context is not None:
            self.add_widget(IconAction('ellipsis', 'Message actions', context))
        self.edge = BoxLayout(size_hint_x=None, width=dp(80))
        self.jump = Action('Go live', self._jump, surface='liveSurface', tone='live')
        self.jump.accessible_name = 'Jump to current audio'
        self.at_edge = Label('At live edge', role='caption', tone='textSecondary')
        self.height = dp(88)

    def _measure(self, *_args: object) -> None:
        """Grows the card when truthful status text wraps in the allocated column.

        Args:
            _args: Native measurement callbacks.
        Returns:
            None
        """
        self.height = max(dp(88), self.body.height + dp(32))

    def _play(self) -> None:
        """Starts at the retained beginning or pauses only this source's output.

        Args:
            None
        Returns:
            None
        """
        playback = self.controller.playback
        if (
            playback.running
            and playback.progress
            and playback.progress.target == self.target
        ):
            playback.stop()
        else:
            playback.play(self.target)
        self.refresh()

    def _jump(self) -> None:
        """Starts at the newest complete PCM frame without consuming skipped content.

        Args:
            None
        Returns:
            None
        """
        position = max(0, self._available - PcmVoice.FRAME_BYTES)
        position -= position % PcmVoice.SAMPLE_BYTES
        self.controller.playback.play(self.target, offset=position)
        self.refresh()

    def update(
        self, size: int, finalized: bool, codec: str | None, status: str
    ) -> None:
        """Updates the existing card from source and output facts without reordering it.

        Args:
            size: Canonically available encoded PCM bytes.
            finalized: Whether the source has a finalized total length.
            codec: Public encoded format identifier.
            status: Truthful receipt or capture status.
        Returns:
            None
        """
        self._available, self._finalized = size, finalized
        playback = self.controller.playback
        progress = playback.progress
        matching = progress is not None and progress.target == self.target
        position = progress.position if matching and progress is not None else 0
        state = progress.state if matching and progress is not None else ''
        self.play.disabled = playback.audio is None or codec != PcmVoice.CODEC
        playing = matching and playback.running
        if playing != self._playing:
            self.play.clear_widgets()
            self.play.add_widget(Symbol('pause' if playing else 'play'))
            self._playing = playing
        self.play.accessible_name = (
            'Pause voice message'
            if matching and playback.running
            else 'Play voice message'
        )
        duration = (
            PcmVoice.duration_ms(size) / PcmVoice.MILLISECONDS
            if size >= 0 and size % PcmVoice.SAMPLE_BYTES == 0
            else 0
        )
        elapsed = PcmVoice.duration_ms(position) / PcmVoice.MILLISECONDS
        self.title.text = (
            'Audio unavailable'
            if self.play.disabled or state == 'unavailable'
            else 'Buffering…'
            if state == 'buffering'
            else 'Voice message'
        )
        self.metadata.text = (
            f'{elapsed:.1f} / {duration:.1f} s · {status}'
            if finalized
            else f'{elapsed:.1f} s / … · {status}'
        )
        if not finalized:
            if self.edge.parent is None:
                self.add_widget(self.edge)
            action = (
                self.jump if position + PcmVoice.FRAME_BYTES < size else self.at_edge
            )
            if action.parent is None:
                self.edge.clear_widgets()
                self.edge.add_widget(action)
            self.jump.disabled = self.play.disabled
        elif self.edge.parent is self:
            self.remove_widget(self.edge)
