import os

class Settings:
    """Static application settings."""

    DEFAULT_PROFILE_NAME = "default"
    PROMPT_SIGN = "$"
    MAX_TOR_RETRIES = 3
    ENABLE_TOR_LOGGING = False

    GREEN, PURPLE, YELLOW, RED, DARK_GREY, CYAN, RESET = "\033[32m", "\033[35m", "\033[33m", "\033[31m", "\033[90m", "\033[36m", "\033[0m"

    @staticmethod
    def get_global_settings_path():
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(pkg_dir, "data")
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
        return os.path.join(data_dir, "settings.json")
