from metor.settings import Settings

class Help:
    """Static help texts."""

    @staticmethod
    def show_chat_help(): 
        return (
            "Chat mode commands:\n"
            f"  {Settings.CYAN}/connect [onion/alias]{Settings.RESET}                           - Connect to a remote peer.\n"
            f"  {Settings.CYAN}/accept [alias]{Settings.RESET}                                  - Accept an incoming connection.\n"
            f"  {Settings.CYAN}/reject [alias]{Settings.RESET}                                  - Reject an incoming connection.\n"
            f"  {Settings.CYAN}/switch [..|alias]{Settings.RESET}                               - Switch focus to another chat.\n"
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
            + Help.show_chat_help() +
            "\n  -> Any other text is sent as a chat message to the currently focused peer.\n\n"
            "Examples:\n"
            "  metor contacts add alice abcdef12345...\n"
            "  metor profile rename default my_main_profile\n"
        )
