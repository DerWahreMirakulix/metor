import os

def get_config_dir():
    """
    Return the path to the configuration directory.
    All data will be stored inside the package folder (in a subfolder 'data').
    """
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    config_dir = os.path.join(pkg_dir, "data")
    if not os.path.exists(config_dir):
        os.makedirs(config_dir)
    return config_dir

def get_hidden_service_dir():
    """
    Return the persistent hidden-service directory path (inside the config folder).
    """
    config_dir = get_config_dir()
    hs_dir = os.path.join(config_dir, "hidden_service")
    if not os.path.exists(hs_dir):
        os.makedirs(hs_dir, mode=0o700)
    else:
        # Ensure permissions are strict enough
        os.chmod(hs_dir, 0o700)
    return hs_dir

def get_history_file():
    """
    Return the path to the history log file (inside the config folder).
    """
    config_dir = get_config_dir()
    return os.path.join(config_dir, "history.log")

def set_chat_lock():
    """
    Create a lock file so that only one chat session is running.
    """
    lock_path = os.path.join(get_config_dir(), "chat.lock")
    with open(lock_path, "w") as f:
        f.write("locked")

def clear_chat_lock():
    """
    Remove the chat lock file.
    """
    lock_path = os.path.join(get_config_dir(), "chat.lock")
    if os.path.exists(lock_path):
        os.remove(lock_path)

def is_chat_running():
    """
    Return True if a chat session is running (lock file exists).
    """
    lock_path = os.path.join(get_config_dir(), "chat.lock")
    return os.path.exists(lock_path)
