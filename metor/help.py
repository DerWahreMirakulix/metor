from metor.settings import Settings

class Help:
    """Static help texts with professional CLI notation."""

    # The absolute column index where the description starts.
    # Adjust this single value to move all descriptions left or right.
    DESC_COLUMN = 46

    @staticmethod
    def _format_line(indent_spaces, cmd, desc, target_column):
        """
        Pads the command string so that the description always starts at the target column,
        compensating for the dynamic indentation length.
        """
        # Calculate how much space is left for the command string
        pad_length = target_column - len(indent_spaces)
        
        # Ensure we don't crash if a command is unexpectedly too long
        pad_length = max(pad_length, len(cmd) + 2) 
        
        padded_cmd = f"{cmd:<{pad_length}}"
        return f"{indent_spaces}{Settings.CYAN}{padded_cmd}{Settings.RESET} - {desc}\n"

    @staticmethod
    def show_chat_help(start=0, intend=2): 
        ind = ' ' * intend * start
        sub_ind = ' ' * intend * (start + 1)
        sub_sub_ind = ' ' * intend * (start + 2)
        
        out = (
            f"{ind}{Settings.PURPLE}Chat Mode:{Settings.RESET}\n\n"
            + f"{ind}* The [alias] can be omitted if you are currently focused on a peer.\n"
            + f"{ind}* Any other text entered is sent to the focused peer.\n\n"
        
            + f"{sub_ind}{Settings.PURPLE}Core Commands:{Settings.RESET}\n"
            + Help._format_line(sub_sub_ind, "/connect <onion|alias>", "Establish a new secure connection.", Help.DESC_COLUMN)
            + Help._format_line(sub_sub_ind, "/accept [alias]", "Accept a background connection request.", Help.DESC_COLUMN)
            + Help._format_line(sub_sub_ind, "/reject [alias]", "Reject a background connection request.", Help.DESC_COLUMN)
            + Help._format_line(sub_sub_ind, "/switch [..|alias]", "Switch focus (use '..' to remove focus).", Help.DESC_COLUMN)
            + Help._format_line(sub_sub_ind, "/end [alias]", "Terminate an active or pending connection.", Help.DESC_COLUMN)
            + Help._format_line(sub_sub_ind, "/connections", "List all active and pending sessions.", Help.DESC_COLUMN)
            + Help._format_line(sub_sub_ind, "/clear", "Wipe the current chat display.", Help.DESC_COLUMN)
            + Help._format_line(sub_sub_ind, "/exit", "Close the UI (Daemon stays active).\n", Help.DESC_COLUMN)
            
            + f"{sub_ind}{Settings.PURPLE}Contact Management:{Settings.RESET}\n"
            + Help._format_line(sub_sub_ind, "/contacts list", "Show saved contacts and temporary RAM aliases.", Help.DESC_COLUMN)
            + Help._format_line(sub_sub_ind, "/contacts add [alias] [onion]", "Save a RAM alias or add a new manual contact.", Help.DESC_COLUMN)
            + Help._format_line(sub_sub_ind, "/contacts rm [alias]", "Remove from disk (active chat reverts to RAM).", Help.DESC_COLUMN)
            + Help._format_line(sub_sub_ind, "/contacts rename [old] <new>", "Change the name of any RAM or Disk alias.", Help.DESC_COLUMN)
        )

        return out
        
    @staticmethod
    def show_main_help(start=0, intend=2):
        ind = ' ' * intend * start
        sub_ind = ' ' * intend * (start + 1)
        
        return (
            "\n"
            + f"{ind}{Settings.GREEN}Metor - Secure Tor Messenger{Settings.RESET}\n\n"
            + f"{ind}Usage: metor [-p PROFILE] <command> [subcommand] [args...]\n\n"
            
            + f"{ind}{Settings.YELLOW}Global Options:{Settings.RESET}\n"
            + Help._format_line(sub_ind, "-p, --profile <name>", "Set the active profile (default: 'default').\n", Help.DESC_COLUMN)
            
            + f"{ind}{Settings.YELLOW}Core Commands:{Settings.RESET}\n"
            + Help._format_line(sub_ind, "metor help", "Show this help overview.", Help.DESC_COLUMN)
            + Help._format_line(sub_ind, "metor daemon", "Start the background Tor & IPC engine.", Help.DESC_COLUMN)
            + Help._format_line(sub_ind, "metor chat", "Enter the interactive multi-chat UI.", Help.DESC_COLUMN)
            + Help._format_line(sub_ind, "metor cleanup", "Kill zombie Tor processes and clear locks.\n", Help.DESC_COLUMN)
            
            + f"{ind}{Settings.YELLOW}Profile & Identity:{Settings.RESET}\n"
            + Help._format_line(sub_ind, "metor address [show|generate]", "View or cycle your hidden service address.", Help.DESC_COLUMN)
            + Help._format_line(sub_ind, "metor profiles [list|add|rm|rename]", "Manage isolated profile environments.", Help.DESC_COLUMN)
            + Help._format_line(sub_ind, "metor history [clear]", "View or wipe the connection event log.\n", Help.DESC_COLUMN)

            + f"{ind}{Settings.YELLOW}External Contact Management:{Settings.RESET}\n"
            + Help._format_line(sub_ind, "metor contacts list", "List all contacts in your address book.", Help.DESC_COLUMN)
            + Help._format_line(sub_ind, "metor contacts add <alias> [onion]", "Add a manual contact or save a running RAM alias.", Help.DESC_COLUMN)
            + Help._format_line(sub_ind, "metor contacts rm <alias>", "Delete contact (active sessions revert to RAM).", Help.DESC_COLUMN)
            + Help._format_line(sub_ind, "metor contacts rename <old> <new>", "Rename a saved contact or active session.\n", Help.DESC_COLUMN)

            + f"{ind}- - -\n\n"
            + Help.show_chat_help(start, intend)
        )
