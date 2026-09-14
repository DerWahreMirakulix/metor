"""Stable editable composer, held recording strip and exact-owner DROP review."""

from collections.abc import Callable

from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout

from metor.core.api import Delivery, MessageDirectionCode
from metor.ui.gui.platform.audio import PcmVoice
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.theme import color, font_path
from metor.ui.gui.widgets import Action, Label, Panel, TextField
from metor.ui.gui.widgets.ptt import PttAction


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
        self.entry.bind(text=self._edit)
        self.ptt = PttAction(controller, refresh)
        self.send = Action(
            'Send Drop' if route.delivery is Delivery.DROP else 'Send',
            lambda: controller.send_text(route.peer or '', route.delivery),
            surface=route.delivery.value,
            tone='onAccent',
            size_hint_x=None,
            width=dp(148),
        )
        self.note = Label('', role='support', tone='textSecondary')
        self.review = Panel(
            orientation='vertical',
            padding=dp(16),
            spacing=dp(8),
            size_hint_y=None,
            height=dp(200),
        )
        self.review.add_widget(Label('Voice Drop · Unsent', role='support'))
        self.preview = Action('Play', self._play_review, disabled=True)
        self.review.add_widget(self.preview)
        self.duration = Label('', role='caption', tone='textSecondary')
        self.review.add_widget(self.duration)
        actions = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(12))
        self.delete = Action(
            'Delete', lambda: self._review_action(False), tone='danger'
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
        self.recheck = Action(
            'Recheck recording',
            lambda: controller.voice.review_actions.check(route.peer or ''),
        )

    def _edit(self, _widget: object, text: str) -> None:
        """Admits a bounded draft while preserving the native cursor on repaint.

        Args:
            _widget: Native input source.
            text: Proposed current text.
        Returns:
            None
        """
        if self._editing:
            return
        state = self.controller.state
        if not state.set_draft(self.route.peer or '', self.route.delivery, text):
            self.entry.text = state.drafts.get(
                (self.route.peer or '', self.route.delivery), ''
            )
            state.status = 'Draft limit reached, finish another draft'
        self.refresh()

    def _review_action(self, send: bool) -> None:
        """Runs one deliberate action on this route's owned recording.

        Args:
            send: Whether the user selected Send rather than Delete.
        Returns:
            None
        """
        self.controller.playback.stop()
        self.controller.voice.review_actions.act(self.route.peer or '', send=send)
        self.refresh()

    def _play_review(self) -> None:
        """Previews the exact owned unsent recording without committing or consuming it.

        Args:
            None
        Returns:
            None
        """
        peer = self.route.peer or ''
        review = self.controller.voice.reviews.get(peer)
        if review is None:
            return
        playback = self.controller.playback
        target = playback.target(
            peer,
            Delivery.DROP,
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
        voice, state = self.controller.voice, self.controller.state
        review = (
            voice.reviews.get(self.route.peer or '')
            if self.route.delivery is Delivery.DROP
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
            self.preview.disabled = playback.audio is None or review.unknown
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
            self.delete.disabled = self.commit.disabled = (
                state.busy or review.unknown or voice.press.active
            )
            self.note.text = (
                'Outcome unconfirmed'
                if review.unknown
                else 'Send or delete this recording to continue.'
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
        action = self.ptt if voice.press.active or not draft.strip() else self.send
        if self.entry.parent is None:
            self.bar.add_widget(self.entry)
        if action is not self._action:
            if self._action is not None:
                self.bar.remove_widget(self._action)
            self.bar.add_widget(action)
            self._action = action
        self.send.disabled = state.busy or voice.press.active
        # Disabling a held native button can swallow its release callback.
        self.ptt.disabled = (
            not voice.press.active and not voice.press.held and not voice.available()
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
            else ''
            if voice.headset_confirmed
            else 'Choose a headset in Settings to record.'
        )
        if self.entry.local_keyboard_visible:
            self.note.text = ''
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
