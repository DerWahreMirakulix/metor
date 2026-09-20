"""Frontend-independent composition of separately authorized platform ports."""

from dataclasses import dataclass
import re

from .actions import HapticsPort, IndicatorPort, ShutdownPort
from .inputs import HardwareInputPort
from .status import HardwareStatusPort


_ADAPTER_ID = re.compile(r'[a-z][a-z0-9_.-]{0,63}')


@dataclass(frozen=True)
class PlatformBindings:
    """Names one validated deployment and its independent typed capabilities.

    Presence of a binding grants no Core authorization. The shutdown port remains
    responsible for deployment-local privilege and exclusive runtime ownership.
    """

    adapter_id: str
    inputs: HardwareInputPort
    shutdown: ShutdownPort | None = None
    status: HardwareStatusPort | None = None
    indicator: IndicatorPort | None = None
    haptics: HapticsPort | None = None

    def __post_init__(self) -> None:
        """Rejects ambiguous provider identities before any port is activated.

        Args:
            None
        Returns:
            None
        """
        if not isinstance(self.adapter_id, str) or not _ADAPTER_ID.fullmatch(
            self.adapter_id
        ):
            raise ValueError('Invalid platform adapter identifier')
