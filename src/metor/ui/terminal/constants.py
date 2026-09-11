"""Terminal rendering and input defaults without host runtime paths."""

from metor.shared import Constants as ContractConstants


class Constants(ContractConstants):
    """Presentation policy independently owned by the Terminal distribution."""

    DEFAULT_COLS: int = 80
    INPUT_SLEEP_SEC: float = 0.02
    INPUT_SELECT_TIMEOUT_SEC: float = 0.0
    UUID_MSG_BYTES: int = 8
