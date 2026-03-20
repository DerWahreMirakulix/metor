import os
import datetime

from metor.profile import ProfileManager
from metor.settings import Settings

class HistoryManager:
    """Manages chat and connection history logging."""
    
    def __init__(self, pm: ProfileManager):
        self.pm = pm

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
            return True, f"History from profile '{self.pm.profile_name}' cleared."
        except IOError:
            return False, f"{Settings.RED}Error:{Settings.RESET} Failed to clear history for profile '{self.pm.profile_name}'."
        
    def update_alias(self, old_alias, new_alias):
        history_file = self.pm.get_history_file()
        if not os.path.exists(history_file):
            return False

        try:
            with open(history_file, "r") as f:
                lines = f.readlines()

            changed = False
            new_lines = []
            
            search_str = f"| remote alias: {old_alias} |"
            replace_str = f"| remote alias: {new_alias} |"

            for line in lines:
                if search_str in line:
                    line = line.replace(search_str, replace_str)
                    changed = True
                new_lines.append(line)

            if changed:
                with open(history_file, "w") as f:
                    f.writelines(new_lines)
            return True
            
        except IOError:
            return False

    def show(self):
        history_lines = self.read_history()
        if not history_lines:
            return f"No history available for profile '{self.pm.profile_name}'."

        lines = [f"History for profile '{self.pm.profile_name}':\n"]
        for line in history_lines:
            lines.append(line.strip())
            
        return "\n".join(lines)
