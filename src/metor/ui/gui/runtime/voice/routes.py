"""Explicit volatile headset endpoint selection with deferred native enumeration."""

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
        if controller.simulator or controller.state.covered or self.voice.running:
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

    def confirm(self) -> bool:
        """Selects actual enumerated endpoints after the user confirms headset routing.

        Args:
            None
        Returns:
            bool: Whether the current supported route was configured.
        """
        inputs = {item.index for item in self.endpoints if item.input_available}
        outputs = {item.index for item in self.endpoints if item.output_available}
        if self.input not in inputs or self.output not in outputs:
            self.voice.controller.state.status = (
                'Choose a headset microphone and output'
            )
            return False
        if self.voice.controller.playback.running:
            self.voice.controller.state.status = (
                'Stop playback before changing the headset'
            )
            return False
        accepted = self.voice.configure(
            HeadsetAudio(self.input, self.output), headset_confirmed=True
        )
        if accepted:
            assert self.output is not None
            self.voice.controller.playback.configure(self.output)
            self.voice.controller.state.status = 'Headset selected. Hold PTT to record.'
        return accepted

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
