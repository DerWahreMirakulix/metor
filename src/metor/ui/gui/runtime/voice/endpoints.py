"""Pure audio-device grouping for friendly choices with retained native variants."""

from dataclasses import dataclass

from metor.client.platform import AudioEndpoint


@dataclass(frozen=True)
class EndpointGroup:
    """One exact device label and its available native routes for one direction."""

    name: str
    preferred: AudioEndpoint
    variants: tuple[AudioEndpoint, ...]


def group_endpoints(
    endpoints: tuple[AudioEndpoint, ...],
    *,
    microphone: bool,
    selected: int | None = None,
) -> tuple[EndpointGroup, ...]:
    """Groups exact device labels without inferring physical identity or support.

    Args:
        endpoints: Inert native descriptors in enumeration order.
        microphone: Whether the choices require input rather than output.
        selected: Explicitly selected native index, retained when compatible.
    Returns:
        Direction-available groups in first-seen order, with all original variants.
        Labels use the supplied device name or the untouched legacy display name.
        The preferred variant is selected when compatible, otherwise the first
        compatible route, otherwise the first unsupported route. No stream opens,
        endpoint changes, or device suitability claims occur.
    """
    groups: dict[str, list[AudioEndpoint]] = {}
    for endpoint in endpoints:
        available = (
            endpoint.input_available if microphone else endpoint.output_available
        )
        if not available:
            continue
        name = endpoint.device_name or endpoint.name
        key = ' '.join(name.split()).casefold()
        groups.setdefault(key, []).append(endpoint)

    result: list[EndpointGroup] = []
    for members in groups.values():
        variants = tuple(members)
        compatible = tuple(
            item
            for item in variants
            if not (item.input_error if microphone else item.output_error)
        )
        preferred = next(
            (item for item in compatible if item.index == selected),
            compatible[0] if compatible else variants[0],
        )
        result.append(
            EndpointGroup(
                name=variants[0].device_name or variants[0].name,
                preferred=preferred,
                variants=variants,
            )
        )
    return tuple(result)
