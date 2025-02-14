import os
import datetime
from metor.config import get_history_file

def log_event(direction, status, onion):
    """
    Log an event.
      - direction: "in" or "out"
      - status: "connected", "rejected", or "disconnected"
      - onion: the identity (onion address or "anonymous")
    """
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {direction} {status} {onion}\n"
    history_file = get_history_file()
    with open(history_file, "a") as f:
        f.write(line)

def read_history():
    """
    Return the history lines (latest first).
    """
    history_file = get_history_file()
    if not os.path.exists(history_file):
        return []
    with open(history_file, "r") as f:
        lines = f.readlines()
    return list(reversed(lines))
