"""Stable editable composer, held recording strip and exact-owner DROP/LIVE review."""

from collections.abc import Callable

from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget

from metor.core.api import Delivery, MessageDirectionCode
from metor.ui.gui.platform.audio import PcmVoice
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.theme import color, font_path
from metor.ui.gui.widgets import Action, Label, Panel, TextField
from metor.ui.gui.widgets.ptt import PttAction
from metor.ui.gui.widgets.symbol import IconAction

# Local Package Imports
from ..audio import show_audio_unavailable


class Composer(BoxLayout):
    """Keeps text focus and initiating input widgets alive across asynchronous updates."""

    def __init__(
        self, controller: GuiController, route: Route, refresh: Callable[[], None]
    ) -> None:
        """Creates one foreground route's input-stage composition.

        Args:
            controller: Current authorized GUI coordinator.
            route: Immutable target captured when the peer pane opens.
            refresh: Coalesced native repaint request.
        Returns:
            None
        """
        super().__init__(orientation='vertical', size_hint_y=None, spacing=dp(8))
        self.controller, self.route, self.refresh = controller, route, refresh
        self._revoked = False
        self.bind(minimum_height=self.setter('height'))
        self._mode = ''
        self._action: Action | None = None
        self._editing = False
        self.bar = Panel(
            orientation='horizontal',
            padding=dp(8),
            spacing=dp(8),
            size_hint_y=None,
            height=dp(64),
        )
        self.entry = TextField(
            font_name=font_path(),
            font_size=sp(15),
            multiline=True,
            foreground_color=color('text'),
            background_color=color('surface'),
            background_normal='',
            background_active='',
            cursor_color=color('focus'),
            hint_text='Message',
            padding=dp(8),
        )
        self.entry.use_bubble = False
        self.entry.use_handles = False
        self.entry.bind(text=self._edit, on_text_validate=self._submit)
        self.entry.submit_on_enter = True
        self.ptt = PttAction(
            controller,
            refresh,
            lambda: show_audio_unavailable(controller, refresh, purpose='recording'),
        )
        self.send = IconAction(
            'send',
            'Send Drop' if route.delivery is Delivery.DROP else 'Send Live message',
            lambda: self._submit(self.entry),
            surface=route.delivery.value,
            tone='onAccent',
        )
        self.note = Label('', role='support', tone='textSecondary')
        self.review = Panel(
            orientation='vertical',
            padding=dp(16),
            spacing=dp(8),
            size_hint_y=None,
            height=dp(200),
        )
        self.review.bind(minimum_height=self.review.setter('height'))
        self.review_title = Label('Voice message · Unsent', role='support')
        self.review.add_widget(self.review_title)
        self.preview = Action('Play', self._play_review, disabled=True)
        self.review.add_widget(self.preview)
        self.duration = Label('', role='caption', tone='textSecondary')
        self.review.add_widget(self.duration)
        actions = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(12))
        self.delete = Action(
            'Discard', lambda: self._review_action(False), tone='danger'
        )
        self.commit = Action(
            'Send Drop',
            lambda: self._review_action(True),
            surface='drop',
            tone='onAccent',
        )
        actions.add_widget(self.delete)
        actions.add_widget(self.commit)
        self.review.add_widget(actions)
        self.alternatives = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(12))
        self.as_drop = Action(
            'Send as Drop',
            lambda: self._review_action(True, Delivery.DROP),
            surface='drop',
            tone='onAccent',
        )
        self.reconnect = Action(
            'Reconnect chat',
            self._reconnect,
        )
        self.recheck = Action(
            'Recheck recording',
            self._recheck,
        )

    def _recheck(self) -> None:
        """Shows readback progress immediately without publishing the recording again."""
        if self._revoked:
            return
        self.controller.voice.review_actions.check(self.route.peer or '')
        self.update()
        self.refresh()

    def _reconnect(self) -> None:
        """Shows admitted LIVE progress in the same frame as the explicit retry."""
        if self._revoked:
            return
        self.controller.live.start(self.route.peer or '')
        self.update()
        self.refresh()

    def _owned_widgets(self) -> set[Widget]:
        """Includes every retained stage, even while another stage is attached."""
        return {
            widget
            for fragment in (
                self.bar,
                self.entry,
                self.review,
                self.alternatives,
                self.note,
                self.send,
                self.ptt,
                self.reconnect,
                self.recheck,
                self.as_drop,
            )
            for widget in fragment.walk(restrict=True)
        }

    def suspend(self) -> None:
        """Revokes input in attached and detached stages without altering the draft."""
        self.ptt.cancel_input()
        for widget in self._owned_widgets():
            if isinstance(widget, Action):
                widget.cancel_input()
            elif isinstance(widget, TextField):
                widget.focus = False
        self.disabled = True

    def revoke(self) -> None:
        """Clears all native stage copies without changing controller-owned drafts."""
        self._revoked = True
        self.suspend()
        self._editing = True
        try:
            for widget in self._owned_widgets():
                if isinstance(widget, (Label, TextField)):
                    widget.text = ''
                if isinstance(widget, Action):
                    widget.accessible_name = ''
        finally:
            self._editing = False
        self.clear_widgets()

    def _edit(self, _widget: object, text: str) -> None:
        """Admits a bounded draft while preserving the native cursor on repaint.

        Args:
            _widget: Native input source.
            text: Proposed current text.
        Returns:
            None
        """
        if self._editing or self._revoked:
            return
        state = self.controller.state
        if not state.set_draft(self.route.peer or '', self.route.delivery, text):
            self.entry.text = state.drafts.get(
                (self.route.peer or '', self.route.delivery), ''
            )
            self.controller.text.report_error(
                self.route.peer or '',
                self.route.delivery,
                'Draft limit reached. Finish another draft before adding more text.',
            )
        else:
            self.controller.text.clear_error(self.route.peer or '', self.route.delivery)
        self.refresh()

    def _submit(self, _widget: object) -> None:
        """Sends the current text draft once while preserving native typing focus.

        Args:
            _widget: Explicit Send or text-field validation source.
        Returns:
            None.
        """
        state = self.controller.state
        if (
            self._revoked
            or state.covered
            or self.controller.client is None
            or state.route != self.route
            or self.controller.voice.press.active
            or self.controller.text.pending(self.route.peer or '', self.route.delivery)
        ):
            return
        self.controller.send_text(self.route.peer or '', self.route.delivery)
        self.update()
        self.refresh()

    def _review_action(self, send: bool, delivery: Delivery | None = None) -> None:
        """Runs one deliberate action on this route's owned recording.

        Args:
            send: Whether the user selected Send rather than Discard.
            delivery: Explicit destination mode, otherwise preserve the recording mode.
        Returns:
            None
        """
        if self._revoked:
            return
        self.controller.playback.stop()
        self.controller.voice.review_actions.act(
            self.route.peer or '', send=send, delivery=delivery
        )
        self.update()
        self.refresh()

    def _play_review(self) -> None:
        """Previews the exact owned unsent recording without committing or consuming it.

        Args:
            None
        Returns:
            None
        """
        if self._revoked:
            return
        peer = self.route.peer or ''
        review = self.controller.voice.reviews.get(peer)
        if review is None:
            return
        playback = self.controller.playback
        if playback.audio is None:
            show_audio_unavailable(self.controller, self.refresh, purpose='playback')
            return
        target = playback.target(
            peer,
            review.binding.delivery,
            MessageDirectionCode.OUT,
            review.binding.msg_id,
            review=True,
        )
        if target is not None:
            if (
                playback.running
                and playback.progress
                and playback.progress.target == target
            ):
                playback.stop()
            else:
                playback.play(target)
        self.refresh()

    def update(self) -> None:
        """Updates stage state without replacing an active input owner.

        Args:
            None
        Returns:
            None
        """
        if self._revoked:
            return
        voice, state = self.controller.voice, self.controller.state
        review = (
            voice.reviews.get(self.route.peer or '')
            if voice.reviews.get(self.route.peer or '') is not None
            and voice.reviews[self.route.peer or ''].binding.delivery
            is self.route.delivery
            else None
        )
        mode = 'review' if review is not None else 'composer'
        if mode != self._mode:
            self.clear_widgets()
            self.add_widget(self.review if review is not None else self.bar)
            self._mode = mode
        if review is not None:
            playback = self.controller.playback
            progress = playback.progress
            matching = (
                progress is not None
                and progress.target.msg_id == review.binding.msg_id
                and progress.target.peer == self.route.peer
            )
            self.preview.disabled = (
                state.covered
                or review.unknown
                or self.controller.calls.active
                or self.controller.calls.media_active
            )
            self.preview.label.text = (
                'Pause' if matching and playback.running else 'Play'
            )
            if (
                matching
                and progress is not None
                and progress.state in {'buffering', 'unavailable'}
            ):
                self.preview.label.text = (
                    'Buffering…'
                    if progress.state == 'buffering'
                    else 'Audio unavailable · Retry'
                )
            self.duration.text = (
                f'{(review.duration_ms or 0) / PcmVoice.MILLISECONDS:.1f} seconds'
            )
            blocked = (
                state.covered or state.busy or review.unknown or voice.press.active
            )
            is_live = review.binding.delivery is Delivery.LIVE
            live_ready = voice.review_actions.live_ready(review)
            self.review_title.text = (
                'Live voice message · Unsent' if is_live else 'Voice Drop · Unsent'
            )
            self.commit.label.text = 'Send Live' if is_live else 'Send Drop'
            self.commit.surface = review.binding.delivery.value
            self.delete.disabled = self.as_drop.disabled = blocked
            self.commit.disabled = blocked or is_live and not live_ready
            self.reconnect.disabled = (
                blocked
                or self.controller.live.pending is not None
                or self.controller.live.starting(self.route.peer or '')
                or not self.controller.live.retry_ready(self.route.peer or '')
            )
            self.reconnect.label.text = self.reconnect.accessible_name = (
                'Connecting…'
                if self.controller.live.starting(self.route.peer or '')
                else 'Reconnect chat'
            )
            self.alternatives.clear_widgets()
            if is_live:
                self.alternatives.add_widget(self.as_drop)
                if not live_ready:
                    self.alternatives.add_widget(self.reconnect)
                if self.alternatives.parent is None:
                    self.review.add_widget(self.alternatives)
            elif self.alternatives.parent is self.review:
                self.review.remove_widget(self.alternatives)
            self.note.text = self.controller.voice.review_actions.notice(
                self.route.peer or ''
            ) or (
                'Outcome unconfirmed'
                if review.unknown
                else 'Live chat ended. Reconnect or explicitly send as Drop.'
                if is_live and not live_ready
                else 'Play, send or discard this recording.'
            )
            if review.unknown and self.recheck.parent is None:
                self.add_widget(self.recheck)
            elif not review.unknown and self.recheck.parent is self:
                self.remove_widget(self.recheck)
            self._notice()
            return
        draft = state.drafts.get((self.route.peer or '', self.route.delivery), '')
        if self.entry.text != draft:
            self._editing = True
            self.entry.text = draft
            self._editing = False
        phase = voice.press.phase.value
        self.entry.readonly = voice.press.active
        self.entry.disabled = voice.press.active
        action = (
            self.ptt if voice.press.active else self.send if draft.strip() else self.ptt
        )
        if self.entry.parent is None:
            self.bar.add_widget(self.entry)
        if action is not self._action:
            if self._action is not None:
                self.bar.remove_widget(self._action)
            self.bar.add_widget(action)
            self._action = action
        self.send.disabled = (
            state.covered
            or self.controller.client is None
            or voice.press.active
            or not draft.strip()
            or self.controller.text.pending(self.route.peer or '', self.route.delivery)
        )
        # Disabling a held native button can swallow its release callback.
        audio_ready = (
            voice.audio is not None
            and voice.headset_confirmed
            and not voice.audio.failed
        )
        self.ptt.disabled = state.covered or (
            not voice.press.active
            and not voice.press.held
            and (
                self.controller.calls.active
                or self.controller.calls.media_active
                or audio_ready
                and not voice.available()
            )
        )
        self.ptt.label.text = (
            'Release to finish'
            if phase == 'recording'
            else 'Starting…'
            if phase == 'starting'
            else 'Finishing…'
            if phase == 'finalizing'
            else 'Release to continue'
            if phase == 'release_required'
            else 'Hold to talk'
        )
        self.note.text = (
            f'Recording · {PcmVoice.duration_ms(voice.accepted_bytes) / PcmVoice.MILLISECONDS:.1f} s'
            if phase == 'recording'
            else 'Finishing recording…'
            if phase == 'finalizing'
            else 'Recording outcome unconfirmed'
            if phase == 'failed'
            else self.controller.text.error(self.route.peer or '', self.route.delivery)
            or self.controller.text.pending_status(
                self.route.peer or '', self.route.delivery
            )
        )
        self._notice()

    def _notice(self) -> None:
        """Keeps idle controls at the bottom edge while review hints follow their panel.

        Args:
            None
        Returns:
            None
        """
        if self.note.text and self.note.parent is None:
            self.add_widget(
                self.note, index=0 if self._mode == 'review' else len(self.children)
            )
        elif not self.note.text and self.note.parent is self:
            self.remove_widget(self.note)
