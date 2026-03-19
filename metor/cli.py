import signal
import sys
import os
import time

if os.name == 'nt':
    import msvcrt
else:
    import termios
    import tty
    import atexit

from metor.config import Settings

class CommandLineInput:
    """Handles non-blocking input with command history and a reactive UI renderer."""
    
    def __init__(self):
        self._initial_prompt = Settings.PROMPT_SIGN + " "
        self._prompt = self._initial_prompt
        self._input_history = []
        self._history_index = -1
        self._current_input = ""
        self._line_counter = 0 
        self._all_msgs = []
        self._current_focus = None

        self._init_terminal()

        # Listen for window resize events to trigger a full redraw (Unix only - Windows sucks)
        if os.name != 'nt':
            signal.signal(signal.SIGWINCH, self._on_resize)

    def _init_terminal(self):
        if os.name != 'nt':
            fd = sys.stdin.fileno()
            old_term_settings = termios.tcgetattr(fd)

            def _reset_terminal():
                termios.tcsetattr(fd, termios.TCSADRAIN, old_term_settings)

            tty.setcbreak(fd)
            atexit.register(_reset_terminal)

    def set_focus(self, alias):
        self._current_focus = alias
        self._prompt = f"{alias}{self._initial_prompt}" if alias else self._initial_prompt
        
        self.repaint()
        
        self.clear_line()
        sys.stdout.write(self._prompt + self._current_input)
        sys.stdout.flush()

    def _format_msg(self, msg_dict):
        GREEN, BLUE, YELLOW, DARK_GREY, RESET, CYAN = "\033[32m", "\033[34m", "\033[33m", "\033[90m", "\033[0m", "\033[36m"
        
        msg_type = msg_dict["msg_type"]
        alias = msg_dict["alias"]
        text = msg_dict["text"]
        is_pending = msg_dict["is_pending"]

        if alias and "{alias}" in text:
            text = text.replace("{alias}", alias)

        if msg_type == "info":
            return f"{YELLOW}info{self._initial_prompt}{RESET}{text}"
            
        if msg_type == "system":
            return f"{CYAN}system{self._initial_prompt}{RESET}{text}"
            
        if msg_type == "raw":
            return text

        is_focused = (alias == self._current_focus) if alias else False

        if not is_focused:
            if msg_type == "self":
                prefix = f"To {alias}{self._initial_prompt}" if alias else f"self{self._initial_prompt}"
            else:
                prefix = f"From {alias}{self._initial_prompt}" if alias else f"remote{self._initial_prompt}"
            return f"{DARK_GREY}{prefix}{text}{RESET}"

        if msg_type == "self":
            prefix = f"To {alias}{self._initial_prompt}" if alias else f"self{self._initial_prompt}"
            if is_pending:
                return f"{prefix}{text}"
            else:
                return f"{GREEN}{prefix}{RESET}{text}"
                
        elif msg_type == "remote":
            prefix = f"From {alias}{self._initial_prompt}" if alias else f"remote{self._initial_prompt}"
            return f"{BLUE}{prefix}{RESET}{text}"

        return text

    def print_message(self, msg, msg_type="raw", alias=None, skip_prompt=False, msg_id=None):
        sys.stdout.write("\r\033[K")
        
        lines = str(msg).splitlines()
        
        for line in lines:
            msg_dict = {
                "line": self._line_counter,
                "text": line,
                "msg_type": msg_type,
                "alias": alias,
                "is_pending": bool(msg_id),
                "msg_id": msg_id
            }
            self._all_msgs.append(msg_dict)

            formatted_msg = self._format_msg(msg_dict)
            sys.stdout.write(formatted_msg + "\n")
            self._line_counter += 1
            
        if not skip_prompt:
            sys.stdout.write(self._prompt + self._current_input)
        sys.stdout.flush()

    def mark_acked(self, msg_id):
        for msg in self._all_msgs:
            if msg.get("msg_id") == msg_id:
                msg["is_pending"] = False
                break
        self.repaint()

    def rename_alias_in_history(self, old_alias, new_alias):
        """Updates ONLY the metadata. The UI will re-render automatically!"""
        for msg in self._all_msgs:
            if msg.get("alias") == old_alias:
                msg["alias"] = new_alias
        self.repaint()

    def repaint(self):
        for msg_dict in self._all_msgs:
            lines_up = self._line_counter - msg_dict["line"]
            if lines_up <= 0:
                continue
                
            formatted_msg = self._format_msg(msg_dict)
            sys.stdout.write(f"\033[{lines_up}A\r\033[K{formatted_msg}\r\033[{lines_up}B")
            
        sys.stdout.write(f"\r{self._prompt}{self._current_input}\033[K")
        sys.stdout.flush()

    def print_prompt(self):
        sys.stdout.write(self._prompt)
        sys.stdout.flush()

    def print_empty_line(self):
        # Defensive: Print a single space instead of an empty line to avoid rendering issues
        self.print_message(" ", msg_type="raw", skip_prompt=True)

    def clear_line(self):
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()

    def clear_screen(self):
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
        self._all_msgs = []
        self._line_counter = 0

    def _on_resize(self, _signum, _frame):
        """Triggered automatically by the OS when the window is resized."""
        self.full_redraw()

    def full_redraw(self):
        """Clears the chaos and rebuilds the UI mathematics completely."""
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()

        old_msgs = self._all_msgs.copy()
        self._all_msgs = []
        self._line_counter = 0

        for msg_dict in old_msgs:
            # Defensive: If text is None or empty, replace with a single space to avoid rendering issues
            text = msg_dict["text"] if msg_dict["text"] else " "
            
            self.print_message(
                msg=text,
                msg_type=msg_dict["msg_type"],
                alias=msg_dict["alias"],
                skip_prompt=True,
                msg_id=msg_dict.get("msg_id")
            )

        self.print_prompt()
        sys.stdout.write(self._current_input)
        sys.stdout.flush()

    def start_loading(self, msg="...", show_prompt=False):
        if show_prompt:
            sys.stdout.write(self._prompt)
        sys.stdout.write(msg)
        sys.stdout.flush()

    def end_loading(self):
        self._flush_input()

    def _flush_input(self):
        if os.name == 'nt':
            while msvcrt.kbhit(): msvcrt.getwch()
        else:
            termios.tcflush(sys.stdin, termios.TCIFLUSH)

    def _get_char(self):
        if os.name == 'nt':
            if msvcrt.kbhit():
                ch = msvcrt.getwch() 
                if ch in ("\x00", "\xe0"):
                    ch2 = msvcrt.getwch()
                    if ch2 == "H": return "SPECIAL:UP"
                    elif ch2 == "P": return "SPECIAL:DOWN"
                    elif ch2 == "K": return "SPECIAL:LEFT"
                    elif ch2 == "M": return "SPECIAL:RIGHT"
                    else: return ""
                return ch
            return None
        else:
            ch1 = sys.stdin.read(1)
            if ch1 == '\x1b':
                ch2 = sys.stdin.read(1)
                if ch2 == '[':
                    ch3 = sys.stdin.read(1)
                    return {'A': 'SPECIAL:UP', 'B': 'SPECIAL:DOWN', 'C': 'SPECIAL:RIGHT', 'D': 'SPECIAL:LEFT'}.get(ch3, 'SPECIAL:UNKNOWN')
                return 'ESC'
            return ch1

    def read_line(self):
        line_chars = []
        cursor_index = 0

        def render_line():
            line_str = ''.join(line_chars)
            sys.stdout.write("\r\033[K" + self._prompt + line_str)
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
                    if self._input_history and self._history_index < len(self._input_history) - 1:
                        self._history_index += 1
                        new_line = self._input_history[-(self._history_index + 1)]
                    else:
                        new_line = self._input_history[0] if self._input_history else ""
                    line_chars = list(new_line)
                    cursor_index = len(line_chars)
                    self._current_input = new_line
                    render_line()
                    continue
                elif key == "DOWN":
                    if self._history_index > 0:
                        self._history_index -= 1
                        new_line = self._input_history[-(self._history_index + 1)]
                    else:
                        self._history_index = -1
                        new_line = ""
                    line_chars = list(new_line)
                    cursor_index = len(line_chars)
                    self._current_input = new_line
                    render_line()
                    continue
                elif key == "LEFT":
                    if cursor_index > 0: cursor_index -= 1
                    render_line()
                    continue
                elif key == "RIGHT":
                    if cursor_index < len(line_chars): cursor_index += 1
                    render_line()
                    continue
                else: continue

            if ch in ("\n", "\r"):
                self.clear_line()
                line = ''.join(line_chars)
                if line.strip(): self._input_history.append(line)
                self._history_index = -1
                self._current_input = ""
                return line
            
            elif ch in ("\b", "\x7f"):
                if cursor_index > 0:
                    del line_chars[cursor_index - 1]
                    cursor_index -= 1
                render_line()
                self._current_input = ''.join(line_chars)
                continue

            else:
                line_chars.insert(cursor_index, ch)
                cursor_index += 1
                render_line()
                self._current_input = ''.join(line_chars)
