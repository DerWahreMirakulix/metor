"""Explicit base-process environment loading after side-effect-free CLI gates."""

import os
from pathlib import Path
import threading

from dotenv import load_dotenv
from metor.utils import Constants

_lock = threading.Lock()
_loaded = False


def initialize_runtime_environment() -> None:
    """Loads local dotenv configuration once before resolving host profiles.

    Args:
        None

    Returns:
        None
    """
    global _loaded
    with _lock:
        if _loaded:
            return
        load_dotenv()
        parent = os.environ.get('METOR_DATA_DIR_PARENT')
        if parent is not None:
            Constants.DATA = Path(parent) / Constants.DATA_DIR
        Constants.TOR_PATH = os.environ.get('METOR_TOR_PATH', '').strip()
        _loaded = True
