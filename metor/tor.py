import os
import shutil
import socket
import time
import socks
import stem.process
import sys

from metor.config import get_tor_data_dir, get_hidden_service_dir, generate_metor_keys, is_chat_running, MAX_TOR_RETRIES, ENABLE_TOR_LOGGING

def get_free_port():
    """
    Return a free port number on localhost.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port

def start_tor():
    """
    Start a Tor process using a persistent hidden-service directory.
    Returns (tor_proc, own_onion, socks_port, incoming_port).
    """
    hs_dir = get_hidden_service_dir()
    data_dir = get_tor_data_dir()
    
    if not os.path.exists(hs_dir):
        os.makedirs(hs_dir, mode=0o700, exist_ok=True)
    try: os.chmod(hs_dir, 0o700)
    except Exception: pass

    generate_metor_keys(hs_dir)

    if not os.path.exists(data_dir):
        os.makedirs(data_dir, mode=0o700, exist_ok=True)
    try: os.chmod(data_dir, 0o700)
    except Exception: pass

    socks_port = get_free_port()
    control_port = get_free_port()
    incoming_port = get_free_port()
    
    config = {
        'SocksPort': str(socks_port),
        'ControlPort': str(control_port),
        'CookieAuthentication': '1',
        'DataDirectory': data_dir,      
        'HiddenServiceDir': hs_dir,
        'HiddenServicePort': f'80 127.0.0.1:{incoming_port}'
    }
    
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tor_cmd = os.path.join(pkg_dir, "tor.exe") if os.name == "nt" else "tor"
    
    def print_tor_output(line):
        if ENABLE_TOR_LOGGING:
            sys.stdout.write(f"\r\033[K\033[36m[TOR-LOG]\033[0m {line}\n")
            sys.stdout.flush()

    tor_proc = None
    for attempt in range(MAX_TOR_RETRIES):
        try:
            tor_proc = stem.process.launch_tor_with_config(
                config=config, timeout=45, take_ownership=True,
                tor_cmd=tor_cmd, init_msg_handler=print_tor_output
            )
            break 
        except OSError as e:
            if attempt < MAX_TOR_RETRIES - 1:
                time.sleep(2)
                continue
            else:
                return None, None, None, None

    hostname_file = os.path.join(hs_dir, "hostname")
    for _ in range(10):
        if os.path.exists(hostname_file): break
        time.sleep(1)
        
    if os.path.exists(hostname_file):
        with open(hostname_file, "r") as f:
            own_onion = f.read().strip()
    else:
        own_onion = "unknown"
        
    return tor_proc, own_onion, socks_port, incoming_port

def stop_tor(tor_proc):
    """
    Stop the given Tor process.
    """
    tor_proc.terminate()

def connect_via_tor(socks_port, onion):
    """
    Connect to a remote peer via Tor.
    """
    s = socks.socksocket()
    s.set_proxy(proxy_type=socks.SOCKS5, addr='127.0.0.1', port=socks_port)
    s.settimeout(10)
    s.connect((onion, 80))
    s.settimeout(None)
    return s

def address_show():
    """
    Show the current onion address.
    """
    hs_dir = get_hidden_service_dir()
    hostname_file = os.path.join(hs_dir, "hostname")
    if os.path.exists(hostname_file):
        with open(hostname_file, "r") as f:
            onion = f.read().strip()
        print(f"Current onion address: {onion}")
    else:
        print("No onion address generated yet. Start chat mode or generate a new address.")

def address_generate():
    """
    Generate a new onion address by resetting the hidden-service directory.
    """
    if is_chat_running():
        print("Changing the address is not possible while a chat is running")
        return
    hs_dir = get_hidden_service_dir()
    if os.path.exists(hs_dir):
        shutil.rmtree(hs_dir)
    os.makedirs(hs_dir)
    # start_tor() returns four values, but we only need the process and onion
    tor_proc, own_onion, _, _ = start_tor()
    stop_tor(tor_proc)
    print(f"New onion address generated: {own_onion}")
