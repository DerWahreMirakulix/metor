import sys
import argparse
import os

from metor.core import run_chat_mode
from metor.config import get_hidden_service_dir, is_chat_running, set_chat_lock, clear_chat_lock
from metor.history import read_history

def show_help():
    help_text = """
Metor - A simple Tor messenger

Available commands:
  metor help                 - Show this help message.
  metor chat                 - Start chat mode.
  metor address show         - Show the current onion address.
  metor address generate     - Generate a new onion address.
  metor history              - Show conversation history.
  metor history clear        - Clear conversation history.

In chat mode, the following commands are available at the metor> prompt:
  /connect [onion] [--anonymous/-a]   Connect to a remote peer.
  /end                                End the current connection.
  /clear                              Clear the chat display.
  /exit                               Exit chat mode.
Any other text is sent as a chat message.
"""
    print(help_text)

def address_show():
    hs_dir = get_hidden_service_dir()
    hostname_file = os.path.join(hs_dir, "hostname")
    if os.path.exists(hostname_file):
        with open(hostname_file, "r") as f:
            onion = f.read().strip()
        print(f"Current onion address: {onion}")
    else:
        print("No onion address generated yet. Start chat mode or generate a new address.")

def address_generate():
    if is_chat_running():
        print("Changing the address is not possible while a chat is running")
        return
    hs_dir = get_hidden_service_dir()
    if os.path.exists(hs_dir):
        import shutil
        shutil.rmtree(hs_dir)
    os.makedirs(hs_dir)
    from metor.core import start_tor, stop_tor
    tor_proc, own_onion = start_tor()
    stop_tor(tor_proc)
    print(f"New onion address generated: {own_onion}")

def show_history():
    history = read_history()
    if not history:
        print("No history available.")
    else:
        for line in history:
            print(line.strip())

def clear_history():
    from metor.config import get_history_file
    history_file = get_history_file()
    if os.path.exists(history_file):
        with open(history_file, "w") as f:
            f.write("")
    print("History cleared.")

def main():
    parser = argparse.ArgumentParser(prog="metor", add_help=False)
    parser.add_argument('command', nargs='?', default='help')
    parser.add_argument('subcommand', nargs='?')
    parser.add_argument('extra', nargs='*')
    args = parser.parse_args()

    if args.command == "help":
        show_help()
    elif args.command == "chat":
        set_chat_lock()
        try:
            run_chat_mode()
        finally:
            clear_chat_lock()
    elif args.command == "address":
        if args.subcommand == "show":
            address_show()
        elif args.subcommand == "generate":
            address_generate()
        else:
            print("Usage: metor address [show|generate]")
    elif args.command == "history":
        if args.subcommand == "clear":
            clear_history()
        else:
            show_history()
    else:
        print("Unknown command. Use 'metor help' to see available commands.")

if __name__ == "__main__":
    main()
