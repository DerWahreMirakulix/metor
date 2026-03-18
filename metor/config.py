import hashlib
import os
import nacl.bindings

# Settings
DEFAULT_PROFILE_NAME = "default"
MAX_TOR_RETRIES = 3
ENABLE_TOR_LOGGING = False

# Global variables
CURRENT_PROFILE = DEFAULT_PROFILE_NAME

def set_profile(profile_name):
    """
    Set the active profile for this session.
    """
    global CURRENT_PROFILE
    # Allow only secure folder names (no slashes etc.)
    safe_name = "".join(c for c in profile_name if c.isalnum() or c in ("-", "_"))
    if safe_name:
        CURRENT_PROFILE = safe_name

def get_config_dir():
    """
    Return the path to the configuration directory.
    All data will be stored inside the package folder (in a subfolder 'data').
    """
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    config_dir = os.path.join(pkg_dir, "data", CURRENT_PROFILE)
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

def get_tor_data_dir():
    """
    Return the path to the dedicated Tor DataDirectory (Sandbox).
    This prevents conflicts with system-wide Tor processes.
    """
    config_dir = get_config_dir()
    data_dir = os.path.join(config_dir, "tor_data")
    if not os.path.exists(data_dir):
        os.makedirs(data_dir, mode=0o700)
    else:
        # Ensure permissions are strict enough for Tor
        os.chmod(data_dir, 0o700)
    return data_dir

def get_history_file():
    """
    Return the path to the history log file (inside the config folder).
    """
    config_dir = get_config_dir()
    return os.path.join(config_dir, "history.log")

def generate_metor_keys(hs_dir = get_hidden_service_dir()):
    """
    Generate a single Ed25519 keypair and save it in both PyNaCl and Tor formats.
    """
    metor_key_path = os.path.join(hs_dir, "metor_secret.key")
    tor_sec_path = os.path.join(hs_dir, "hs_ed25519_secret_key")
    tor_pub_path = os.path.join(hs_dir, "hs_ed25519_public_key")
    
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

def get_metor_key(hs_dir = get_hidden_service_dir()):
    hs_dir = get_hidden_service_dir()
    key_path = os.path.join(hs_dir, "metor_secret.key")
    
    with open(key_path, "rb") as f:
        return f.read()

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

def chat_help(): 
    return (
        "Chat mode commands:\n"
        "  /connect [onion]           - Connect to a remote peer.\n"
        "  /end                       - End the current connection.\n"
        "  /clear                     - Clear the chat display.\n"
        "  /exit                      - Exit chat mode.\n"
    )
    
def help():
    return (
        "Metor - A simple Tor messenger\n\n"
        "Usage: metor [-p PROFILE] command [subcommand]\n\n"
        "Global Options:\n"
        "  -p, --profile <name>       Set the active profile (default: 'default').\n"
        "                             Keeps history, onion addresses, and locks separated.\n\n"
        "Available commands:\n"
        "  metor help                 - Show this help message.\n"
        "  metor chat                 - Start chat mode.\n"
        "  metor address show         - Show the current onion address.\n"
        "  metor address generate     - Generate a new onion address.\n"
        "  metor history              - Show conversation history.\n"
        "  metor history clear        - Clear conversation history.\n\n"
        + chat_help() +
        "\n  -> Any other text is sent as a chat message.\n\n"
        "Examples:\n"
        "  metor -p alice chat\n"
        "  metor -p bob address show\n"
    )