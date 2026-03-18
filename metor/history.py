import os
import datetime

from metor.config import get_history_file

def log_event(acting_peer, status, onion, reason=""):
    """
    Log an event.
      - acting_peer: "self" or "remote"
      - status: "connected", "rejected", or "disconnected"
      - onion: the identity (onion address)
      - reason: optional reason for rejection
    """
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {status}"
    if acting_peer == "remote":
        line += " by remote peer"
    line += f" | remote peer: {onion}"
    if reason:
        line += f" | reason: {reason}"
    line += "\n"
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

def show_history():
    """
    Show the history of connection events.
    """
    history = read_history()
    if not history:
        print("No history available.")
    else:
        for line in history:
            print(line.strip())

def clear_history():
    """
    Clear the history by truncating the history file.
    """
    history_file = get_history_file()
    if os.path.exists(history_file):
        with open(history_file, "w") as f:
            f.write("")
    print("History cleared.")
