import sys
import os
import time

if os.name == 'nt':
    import msvcrt
else:
    import termios
    import tty
    import atexit

class CommandLineInput:
    """
    Handles non-blocking input with command history and arrow-key navigation.
    """
    def __init__(self, prompt="> "):
        self.chat_help = (
            "Chat mode commands:\n"
            "  /connect [onion]                    Connect to a remote peer\n"
            "  /end                                End the current connection\n"
            "  /clear                              Clear the chat display\n"
            "  /exit                               Exit chat mode\n"
        )
        self.help = (
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
            + self.chat_help +
            "Any other text is sent as a chat message.\n\n"
            "Examples:\n"
            "  metor -p alice chat\n"
            "  metor -p bob address show\n"
        )
        self.prompt = prompt
        self.input_history = []
        self.history_index = -1
        self.current_input = ""
        self.line_counter = 0 
        self.pending_msgs = {}

        self._init_terminal()

    def _init_terminal(self):
        """
        Set up the terminal for non-blocking input and ensure it resets on exit.
        """
        if os.name != 'nt':
            fd = sys.stdin.fileno()
            old_term_settings = termios.tcgetattr(fd)

            def _reset_terminal():
                termios.tcsetattr(fd, termios.TCSADRAIN, old_term_settings)

            tty.setcbreak(fd)
            atexit.register(_reset_terminal)

    def print_message(self, msg, skip_prompt=False, msg_id=None):
        """
        Print a message to the console with colored prefixes.
        If msg_id is provided, it marks it as pending.
        """
        GREEN, BLUE, YELLOW, WHITE, RESET = "\033[32m", "\033[34m", "\033[33m", "\033[37m", "\033[0m"
        
        sys.stdout.write("\r\033[K")
        
        if msg.startswith("self_pending>"):
            msg = msg.replace("self_pending>", f"{WHITE}self>{RESET}", 1)
            if msg_id:
                self.pending_msgs[msg_id] = (self.line_counter, msg)
                
        elif msg.startswith("self>"):
            msg = msg.replace("self>", f"{GREEN}self>{RESET}", 1)
        elif msg.startswith("remote>"):
            msg = msg.replace("remote>", f"{BLUE}remote>{RESET}", 1)
        elif msg.startswith("info>"):
            msg = msg.replace("info>", f"{YELLOW}info>{RESET}", 1)
            
        sys.stdout.write(msg + "\n")
        self.line_counter += 1
        
        if not skip_prompt:
            sys.stdout.write(self.prompt + self.current_input)
        sys.stdout.flush()

    def _update_message(self, msg_id):
        """
        Moves the cursor up to the pending message, rewrites it in green, 
        and returns to the prompt.
        """
        if msg_id not in self.pending_msgs:
            return
            
        target_line, original_msg = self.pending_msgs.pop(msg_id)
        GREEN, WHITE, RESET = "\033[32m", "\033[37m", "\033[0m"
        
        # Calculate how many lines we need to move up (+1 because of the prompt)
        lines_up = self.line_counter - target_line
        
        # Move up n lines and clear the line
        sys.stdout.write(f"\033[{lines_up}A\r\033[K")
        
        # Write the message in green (replace the white "self>" with green)
        green_msg = original_msg.replace(f"{WHITE}self>{RESET}", f"{GREEN}self>{RESET}", 1)
        sys.stdout.write(green_msg)
        
        # Move down n lines to the prompt
        sys.stdout.write(f"\033[{lines_up}B\r\033[K")
        
        # Restore the prompt
        sys.stdout.write(self.prompt + self.current_input)
        sys.stdout.flush()

    def print_prompt(self):
        """
        Print the prompt and current input.
        """
        sys.stdout.write(self.prompt)
        sys.stdout.flush()

    def clear_line(self):
        """
        Clear the current input line.
        """
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()

    def start_loading(self, msg="..."):
        """
        Display a loading message and flush input to prevent interference.
        """
        sys.stdout.write(msg)
        sys.stdout.flush()

    def end_loading(self):
        """
        Clear the loading message and flush input.
        """
        self._flush_input()

    def _flush_input(self):
        """
        Discard any pending keyboard input.
        """
        if os.name == 'nt':
            while msvcrt.kbhit():
                msvcrt.getwch()
        else:
            termios.tcflush(sys.stdin, termios.TCIFLUSH)

    def _get_char(self):
        """
        Return a single character or a special marker if an arrow key is pressed.
        """
        if os.name == 'nt':
            if msvcrt.kbhit():
                ch = msvcrt.getwch()  # Unicode version (does not echo)
                if ch in ("\x00", "\xe0"):
                    ch2 = msvcrt.getwch()
                    if ch2 == "H":
                        return "SPECIAL:UP"
                    elif ch2 == "P":
                        return "SPECIAL:DOWN"
                    elif ch2 == "K":
                        return "SPECIAL:LEFT"
                    elif ch2 == "M":
                        return "SPECIAL:RIGHT"
                    else:
                        return ""
                return ch
            return None
        else:
            ch1 = sys.stdin.read(1)
            if ch1 == '\x1b':
                ch2 = sys.stdin.read(1)
                if ch2 == '[':
                    ch3 = sys.stdin.read(1)
                    return {
                        'A': 'SPECIAL:UP',
                        'B': 'SPECIAL:DOWN',
                        'C': 'SPECIAL:RIGHT',
                        'D': 'SPECIAL:LEFT'
                    }.get(ch3, 'SPECIAL:UNKNOWN')
                return 'ESC'
            return ch1

    def read_line(self):
        """
        Read a line non-blockingly while handling arrow keys and history.
        Returns the completed input line.
        """
        line_chars = []
        cursor_index = 0

        def render_line():
            line_str = ''.join(line_chars)
            sys.stdout.write("\r\033[K" + self.prompt + line_str)
            if cursor_index < len(line_chars):
                move_left = len(line_chars) - cursor_index
                sys.stdout.write(f"\033[{move_left}D")
            sys.stdout.flush()

        while True:
            ch = self._get_char()

            if ch is None:
                time.sleep(0.05)
                continue

            if ch.startswith("SPECIAL:"):
                key = ch.split(":")[1]
                if key == "UP":
                    if self.input_history and self.history_index < len(self.input_history) - 1:
                        self.history_index += 1
                        new_line = self.input_history[-(self.history_index + 1)]
                    else:
                        new_line = self.input_history[0] if self.input_history else ""
                    line_chars = list(new_line)
                    cursor_index = len(line_chars)
                    self.current_input = new_line
                    render_line()
                    continue
                elif key == "DOWN":
                    if self.history_index > 0:
                        self.history_index -= 1
                        new_line = self.input_history[-(self.history_index + 1)]
                    else:
                        self.history_index = -1
                        new_line = ""
                    line_chars = list(new_line)
                    cursor_index = len(line_chars)
                    self.current_input = new_line
                    render_line()
                    continue
                elif key == "LEFT":
                    if cursor_index > 0:
                        cursor_index -= 1
                    render_line()
                    continue
                elif key == "RIGHT":
                    if cursor_index < len(line_chars):
                        cursor_index += 1
                    render_line()
                    continue
                else:
                    continue

            if ch in ("\n", "\r"):
                self.clear_line()
                line = ''.join(line_chars)
                if line.strip():
                    self.input_history.append(line)
                self.history_index = -1
                self.current_input = ""
                return line
            
            elif ch in ("\b", "\x7f"):
                if cursor_index > 0:
                    del line_chars[cursor_index - 1]
                    cursor_index -= 1
                render_line()
                self.current_input = ''.join(line_chars)
                continue

            else:
                line_chars.insert(cursor_index, ch)
                cursor_index += 1
                render_line()
                self.current_input = ''.join(line_chars)
