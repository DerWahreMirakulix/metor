import hashlib
import os
import shutil
import json
import nacl.bindings

class Settings:
    """Static application settings."""

    DEFAULT_PROFILE_NAME = "default"
    PROMPT_SIGN = "$"
    MAX_TOR_RETRIES = 3
    ENABLE_TOR_LOGGING = False

    GREEN, BLUE, YELLOW, RED, DARK_GREY, CYAN, RESET = "\033[32m", "\033[34m", "\033[33m", "\033[31m", "\033[90m", "\033[36m", "\033[0m"

class ProfileManager:
    """Manages profile directories, configurations, and session locks."""
    
    def __init__(self, profile_name=None):
        self.profile_name = profile_name if profile_name else self.load_default_profile()

    @staticmethod
    def get_global_settings_path():
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(pkg_dir, "data")
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
        return os.path.join(data_dir, "settings.json")

    @classmethod
    def load_default_profile(cls):
        settings_path = cls.get_global_settings_path()
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
            return False, "Invalid profile name."
            
        settings_path = cls.get_global_settings_path()
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

    def get_chat_lock_path(self):
        return os.path.join(self.get_config_dir(), "chat.lock")

    def set_chat_lock(self):
        with open(self.get_chat_lock_path(), "w") as f:
            f.write("locked")

    def clear_chat_lock(self):
        lock_path = self.get_chat_lock_path()
        if os.path.exists(lock_path):
            os.remove(lock_path)

    def is_chat_running(self):
        return os.path.exists(self.get_chat_lock_path())

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
            return False, "Invalid profile name."
        
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
        target_dir = os.path.join(pkg_dir, "data", safe_name)
        if os.path.exists(target_dir):
            return False, f"Profile '{safe_name}' already exists."
            
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
            return False, f"Profile '{safe_old}' does not exist."
        if os.path.exists(new_dir):
            return False, f"Profile '{safe_new}' already exists."
            
        if cls(safe_old).is_chat_running():
            return False, f"Cannot rename profile '{safe_old}' while its chat session is running!"
            
        os.rename(old_dir, new_dir)
        return True, f"Profile '{safe_old}' successfully renamed to '{safe_new}'."

    @classmethod
    def remove_profile_folder(cls, name):
        safe_name = "".join(c for c in name if c.isalnum() or c in ("-", "_"))
        if not safe_name:
            return False, "Invalid profile name."
            
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
        target_dir = os.path.join(pkg_dir, "data", safe_name)
        
        if not os.path.exists(target_dir):
            return False, f"Profile '{safe_name}' does not exist."
            
        if cls(safe_name).is_chat_running():
            return False, f"Cannot remove profile '{safe_name}' while its chat session is running!"
            
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

class KeyManager:
    """Manages Ed25519 cryptographic keys."""
    
    def __init__(self, profile_manager: ProfileManager):
        self.pm = profile_manager
        self.hs_dir = self.pm.get_hidden_service_dir()

    def generate_keys(self):
        metor_key_path = os.path.join(self.hs_dir, "metor_secret.key")
        tor_sec_path = os.path.join(self.hs_dir, "hs_ed25519_secret_key")
        tor_pub_path = os.path.join(self.hs_dir, "hs_ed25519_public_key")
        
        if os.path.exists(metor_key_path) and os.path.exists(tor_sec_path):
            return

        seed = os.urandom(32)
        public_key, pynacl_secret_key = nacl.bindings.crypto_sign_seed_keypair(seed)
        
        h = hashlib.sha512(seed).digest()
        scalar = bytearray(h[:32])
        scalar[0] &= 248
        scalar[31] &= 127
        scalar[31] |= 64
        expanded_key = bytes(scalar) + h[32:]
        
        with open(metor_key_path, "wb") as f:
            f.write(pynacl_secret_key)
        with open(tor_sec_path, "wb") as f:
            f.write(b"== ed25519v1-secret: type0 ==\x00\x00\x00")
            f.write(expanded_key)
        with open(tor_pub_path, "wb") as f:
            f.write(b"== ed25519v1-public: type0 ==\x00\x00\x00")
            f.write(public_key)

    def get_metor_key(self):
        key_path = os.path.join(self.hs_dir, "metor_secret.key")
        with open(key_path, "rb") as f:
            return f.read()

class HelpMenu:
    """Static help texts."""

    @staticmethod
    def show_chat_help(): 
        return (
            "Chat mode commands:\n"
            f"  {Settings.CYAN}/connect [onion/alias]{Settings.RESET}                           - Connect to a remote peer.\n"
            f"  {Settings.CYAN}/accept [alias]{Settings.RESET}                                  - Accept an incoming connection.\n"
            f"  {Settings.CYAN}/reject [alias]{Settings.RESET}                                  - Reject an incoming connection.\n"
            f"  {Settings.CYAN}/switch [alias]{Settings.RESET}                                  - Switch focus to another chat.\n"
            f"  {Settings.CYAN}/contacts [list|add|rm|rename]{Settings.RESET}                   - Manage your address book.\n"
            f"  {Settings.CYAN}/connections{Settings.RESET}                                     - Show all active/pending connections.\n"
            f"  {Settings.CYAN}/end [alias]{Settings.RESET}                                     - End the current or specified chat.\n"
            f"  {Settings.CYAN}/clear{Settings.RESET}                                           - Clear the chat display.\n"
            f"  {Settings.CYAN}/exit{Settings.RESET}                                            - Exit chat mode.\n"
        )
        
    @staticmethod
    def show_main_help():
        return (
            "Metor - A simple, secure Tor messenger\n\n"
            "Usage: metor [-p PROFILE] command [subcommand] [args...]\n\n"
            "Global Options:\n"
            f"  {Settings.CYAN}-p, --profile <name>{Settings.RESET}         Set the active profile (default: 'default').\n"
            "                               Keeps history, onion addresses, contacts, and locks separated.\n\n"
            "Available commands:\n"
            f"  {Settings.CYAN}metor help{Settings.RESET}                                       - Show this help message.\n"
            f"  {Settings.CYAN}metor chat{Settings.RESET}                                       - Start chat mode.\n"
            f"  {Settings.CYAN}metor address show{Settings.RESET}                               - Show the current onion address.\n"
            f"  {Settings.CYAN}metor address generate{Settings.RESET}                           - Generate a new onion address.\n"
            f"  {Settings.CYAN}metor history [clear]{Settings.RESET}                            - Show or clear connection history.\n"
            f"  {Settings.CYAN}metor contacts [list|add|rm|rename]{Settings.RESET}              - Manage your address book.\n"
            f"  {Settings.CYAN}metor profile [list|add|rm|rename|set-default]{Settings.RESET}   - Manage your profiles.\n\n"
            + HelpMenu.show_chat_help() +
            "\n  -> Any other text is sent as a chat message to the currently focused peer.\n\n"
            "Examples:\n"
            "  metor contacts add alice abcdef12345...\n"
            "  metor profile rename default my_main_profile\n"
        )
