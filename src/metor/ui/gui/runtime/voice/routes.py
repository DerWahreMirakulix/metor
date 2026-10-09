"""Explicit volatile audio endpoint selection with deferred native enumeration."""

from typing import TYPE_CHECKING

from metor.core.api import IpcEvent
from metor.client.platform import AudioEndpoint
from metor.ui.gui.platform.audio import HeadsetAudio
from metor.ui.gui.state.mailbox import Update

if TYPE_CHECKING:
    from .controller import VoiceController


class AudioRoutes:
    """Keeps only current route descriptors and explicit user endpoint choices."""

    def __init__(self, voice: 'VoiceController') -> None:
        """Creates an unconfigured route without probing native libraries.

        Args:
            voice: Current GUI Voice owner.
        Returns:
            None
        """
        self.voice = voice
        self.endpoints: tuple[AudioEndpoint, ...] = ()
        self.input: int | None = None
        self.output: int | None = None
        self.scanned = False

    def scan(self) -> bool:
        """Queries native endpoints off the GUI loop after explicit user intent.

        Args:
            None
        Returns:
            bool: Whether the bounded scan operation was admitted.
        """
        controller = self.voice.controller
        if controller.simulator or controller.state.covered or self.blocked:
            return False
        generation = controller.state.generation

        def probe() -> IpcEvent | None:
            """Hands off native route descriptors without pretending they are IPC facts.

            Args:
                None
            Returns:
                IpcEvent | None: Native results use their dedicated typed mailbox field.
            """
            try:
                endpoints = HeadsetAudio.endpoints()
                status = '' if endpoints else 'No audio devices are available'
            except Exception:
                endpoints = ()
                status = 'Audio devices could not be opened'
            controller.mailbox.put(
                Update(
                    generation, 'audio-routes', status=status, audio_endpoints=endpoints
                )
            )
            return None

        return controller.submit('audio-scan', probe)

    @property
    def blocked(self) -> bool:
        """Reports media owners that must finish before a route can be replaced."""
        controller = self.voice.controller
        return bool(
            self.voice.running
            or self.voice.press.active
            or controller.playback.running
            or controller.calls.active
            or controller.calls.media_active
        )

    def select(self, endpoint: int, *, microphone: bool) -> bool:
        """Applies one explicit compatible direction without opening either stream.

        Args:
            endpoint: Current native endpoint index selected in the chooser.
            microphone: Whether this selection replaces input rather than output.
        Returns:
            bool: Whether the idle route was installed; playback needs only output.
        """
        controller = self.voice.controller
        if controller.state.covered or self.blocked:
            return False
        valid = any(
            item.index == endpoint
            and (item.input_available if microphone else item.output_available)
            and not (item.input_error if microphone else item.output_error)
            for item in self.endpoints
        )
        if not valid:
            return False
        selected_input = endpoint if microphone else self.input
        selected_output = self.output if microphone else endpoint
        if not self.voice.configure(
            HeadsetAudio(selected_input, selected_output),
            headset_confirmed=selected_input is not None,
        ):
            return False
        if not microphone:
            assert selected_output is not None
            controller.playback.configure(selected_output)
        self.input, self.output = selected_input, selected_output
        return True

    def install(self, update: Update) -> bool:
        """Installs only the generation-validated native endpoint result.

        Args:
            update: Result from the current activation's explicit scan.
        Returns:
            bool: Whether the result belongs to route selection.
        """
        if update.audio_endpoints is None:
            return False
        self.endpoints = update.audio_endpoints
        self.scanned = True
        self.voice.controller.state.status = update.status
        return True
