import os
import shutil
import json

from metor.settings import Settings

class ProfileManager:
    """Manages profile directories, configurations, and session locks."""
    
    def __init__(self, profile_name=None):
        self.profile_name = profile_name if profile_name else self.load_default_profile()

    @classmethod
    def load_default_profile(cls):
        settings_path = Settings.get_global_settings_path()
        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                    return settings.get("default_profile", Settings.DEFAULT_PROFILE_NAME)
            except (json.JSONDecodeError, IOError):
                pass
        return Settings.DEFAULT_PROFILE_NAME

    @classmethod
    def set_default_profile(cls, profile_name):
        safe_name = "".join(c for c in profile_name if c.isalnum() or c in ("-", "_"))
        if not safe_name:
            return False, f"{Settings.RED}Error:{Settings.RESET} Invalid profile name."
            
        settings_path = Settings.get_global_settings_path()
        settings = {}
        
        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    settings = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
                
        settings["default_profile"] = safe_name
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4)
            
        return True, f"Default profile permanently set to '{safe_name}'."

    def get_config_dir(self):
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
        config_dir = os.path.join(pkg_dir, "data", self.profile_name)
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
        return config_dir
    
    def get_daemon_port_file(self):
        return os.path.join(self.get_config_dir(), "daemon.port")

    def set_daemon_port(self, port):
        with open(self.get_daemon_port_file(), "w") as f:
            f.write(str(port))

    def get_daemon_port(self):
        port_file = self.get_daemon_port_file()
        if os.path.exists(port_file):
            try:
                with open(port_file, "r") as f:
                    return int(f.read().strip())
            except Exception: pass
        return None

    def clear_daemon_port(self):
        port_file = self.get_daemon_port_file()
        if os.path.exists(port_file):
            os.remove(port_file)

    def is_daemon_running(self):
        return os.path.exists(self.get_daemon_port_file())

    def get_hidden_service_dir(self):
        hs_dir = os.path.join(self.get_config_dir(), "hidden_service")
        if not os.path.exists(hs_dir):
            os.makedirs(hs_dir, mode=0o700)
        else:
            os.chmod(hs_dir, 0o700)
        return hs_dir

    def get_tor_data_dir(self):
        data_dir = os.path.join(self.get_config_dir(), "tor_data")
        if not os.path.exists(data_dir):
            os.makedirs(data_dir, mode=0o700)
        else:
            os.chmod(data_dir, 0o700)
        return data_dir

    def get_history_file(self):
        return os.path.join(self.get_config_dir(), "history.log")

    @staticmethod
    def get_all_profiles():
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(pkg_dir, "data")
        if not os.path.exists(data_dir):
            return []
        return [d for d in os.listdir(data_dir) if os.path.isdir(os.path.join(data_dir, d))]

    @staticmethod
    def add_profile_folder(name):
        safe_name = "".join(c for c in name if c.isalnum() or c in ("-", "_"))
        if not safe_name:
            return False, f"{Settings.RED}Error:{Settings.RESET} Invalid profile name."
        
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
        target_dir = os.path.join(pkg_dir, "data", safe_name)
        if os.path.exists(target_dir):
            return False, f"{Settings.RED}Error:{Settings.RESET} Profile '{safe_name}' already exists."
            
        os.makedirs(target_dir)
        return True, f"Profile '{safe_name}' successfully created."

    @classmethod
    def rename_profile_folder(cls, old_name, new_name):
        safe_old = "".join(c for c in old_name if c.isalnum() or c in ("-", "_"))
        safe_new = "".join(c for c in new_name if c.isalnum() or c in ("-", "_"))
        
        if not safe_old or not safe_new:
            return False, "Invalid profile names."
            
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
        old_dir = os.path.join(pkg_dir, "data", safe_old)
        new_dir = os.path.join(pkg_dir, "data", safe_new)
        
        if not os.path.exists(old_dir):
            return False, f"{Settings.RED}Error:{Settings.RESET}  Profile '{safe_old}' does not exist."
        if os.path.exists(new_dir):
            return False, f"{Settings.RED}Error:{Settings.RESET} Profile '{safe_new}' already exists."
            
        if cls(safe_old).is_daemon_running():
            return False, f"{Settings.RED}Error:{Settings.RESET} Cannot rename profile '{safe_old}' while its daemon is running!"
            
        os.rename(old_dir, new_dir)
        return True, f"Profile '{safe_old}' successfully renamed to '{safe_new}'."

    @classmethod
    def remove_profile_folder(cls, name):
        safe_name = "".join(c for c in name if c.isalnum() or c in ("-", "_"))
        if not safe_name:
            return False, f"{Settings.RED}Error:{Settings.RESET} Invalid profile name."
            
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
        target_dir = os.path.join(pkg_dir, "data", safe_name)
        
        if not os.path.exists(target_dir):
            return False, f"{Settings.RED}Error:{Settings.RESET} Profile '{safe_name}' does not exist."
            
        if cls(safe_name).is_daemon_running():
            return False, f"{Settings.RED}Error:{Settings.RESET} Cannot remove profile '{safe_name}' while its daemon is running!"
            
        shutil.rmtree(target_dir)
        return True, f"Profile '{safe_name}' successfully removed."
    
    @classmethod
    def show(cls, active_profile=None):
        active = active_profile if active_profile else cls.load_default_profile()
        profiles = cls.get_all_profiles()
        if not profiles:
            return "No profiles found."
        
        lines = ["Available profiles:"]
        for p in profiles:
            marker = "*" if p == active else " "
            if p == active:
                lines.append(f" {Settings.CYAN}{marker} {p}{Settings.RESET}")
            else:
                lines.append(f"   {p}")
        
        return "\n".join(lines)
