import os
import datetime
from metor.config import ProfileManager

class HistoryManager:
    """Manages chat and connection history logging."""
    
    def __init__(self, profile_manager: ProfileManager):
        self.pm = profile_manager

    def log_event(self, status, alias, onion, reason=""):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {status} | remote alias: {alias} | remote identity: {onion}"
        if reason:
            line += f" | reason: {reason}"
        line += "\n"
        
        history_file = self.pm.get_history_file()
        with open(history_file, "a") as f:
            f.write(line)

    def read_history(self):
        history_file = self.pm.get_history_file()
        if not os.path.exists(history_file):
            return []
        try:
            with open(history_file, "r") as f:
                lines = f.readlines()
            return list(reversed(lines))
        except IOError:
            return []

    def clear_history(self):
        history_file = self.pm.get_history_file()
        try:
            if os.path.exists(history_file):
                with open(history_file, "w") as f:
                    f.write("")
            return True
        except IOError:
            return False

    def show(self):
        history_lines = self.read_history()
        if not history_lines:
            return f"No history available for profile '{self.pm.profile_name}'."
        
        return_value = f"History for profile '{self.pm.profile_name}':\n"
        for line in history_lines:
            return_value += line.strip() + "\n"
        return return_value
