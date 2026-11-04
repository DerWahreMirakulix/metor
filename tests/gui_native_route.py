"""Generic, side-effect-free route selection for native audio acceptance probes."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from metor.client.platform import AudioEndpoint


@dataclass(frozen=True)
class SelectedAudioRoute:
    """Exact currently enumerated input/output endpoints admitted for a probe."""

    source: AudioEndpoint
    sink: AudioEndpoint


def select_audio_route(
    endpoints: Sequence[AudioEndpoint],
    input_index: int,
    output_index: int,
    *,
    headset_confirmed: bool,
    validate_format: Callable[[int, int], None],
) -> SelectedAudioRoute:
    """Selects explicit capable endpoints without opening either native stream."""
    if not headset_confirmed:
        raise RuntimeError('Explicit headset-route confirmation is required')
    by_index = {endpoint.index: endpoint for endpoint in endpoints}
    source = by_index.get(input_index)
    sink = by_index.get(output_index)
    if source is None or sink is None:
        raise RuntimeError('The selected audio route is no longer enumerated')
    if not source.input_available:
        raise RuntimeError('The selected input endpoint has no capture direction')
    if not sink.output_available:
        raise RuntimeError('The selected output endpoint has no playback direction')
    validate_format(source.index, sink.index)
    return SelectedAudioRoute(source, sink)


def verify_gui_module_origin(
    module_file: str,
    *,
    mode: str,
    checkout: Path,
    environment_root: Path,
) -> None:
    """Rejects source/installed acceptance when the imported GUI has wrong origin."""
    module_path = Path(module_file).resolve()
    source_root = (checkout / 'src').resolve()
    if mode == 'source':
        if not module_path.is_relative_to(source_root):
            raise RuntimeError('Source mode did not load the checkout GUI')
        return
    if mode != 'installed':
        raise RuntimeError('Unknown native probe mode')
    if module_path.is_relative_to(checkout.resolve()):
        raise RuntimeError('Installed mode loaded GUI code from the checkout')
    if not module_path.is_relative_to(environment_root.resolve()):
        raise RuntimeError('Installed mode loaded GUI code outside its environment')
