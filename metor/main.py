import argparse

from metor.config import set_chat_lock, clear_chat_lock, set_profile, help, DEFAULT_PROFILE_NAME
from metor.chat import run_chat_mode
from metor.history import show_history, clear_history
from metor.tor import address_show, address_generate

def main():
    """
    Main entry point for the metor CLI.
    """
    parser = argparse.ArgumentParser(prog="metor", add_help=False)
    parser.add_argument('-p', '--profile', default=DEFAULT_PROFILE_NAME)
    parser.add_argument('command', nargs='?', default='help')
    parser.add_argument('subcommand', nargs='?')
    parser.add_argument('extra', nargs='*')
    args = parser.parse_args()

    # This ensures that get_hidden_service_dir(), read_history(), etc., will now use the correct subfolder.
    set_profile(args.profile)

    if args.command == "help":
        print(help())
    elif args.command == "chat":
        # block the chat.lock of the respective profile!
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
