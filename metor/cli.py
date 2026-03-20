import shutil
import signal
import sys
import os
import time
import re
import threading

if os.name == 'nt':
    import msvcrt
else:
    import termios
    import tty
    import atexit

from metor.settings import Settings

class CommandLineInput:
    """Handles non-blocking input with command history and a reactive UI renderer."""
    
    def __init__(self):
        self._initial_prompt = Settings.PROMPT_SIGN + " "
        self._prompt = self._initial_prompt
        self._input_history = []
        self._history_index = -1
        self._current_input = ""
        self._all_msgs = []
        self._current_focus = None
        self._is_redrawing = False
        self._last_cols = shutil.get_terminal_size().columns

        self._line_chars = []
        self._cursor_index = 0
        self._last_visual_lines = 1
        self._print_lock = threading.Lock()
        
        self._ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

        self._init_terminal()

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
        with self._print_lock:
            self._current_focus = alias
            self._prompt = f"{alias}{self._initial_prompt}" if alias else self._initial_prompt
        self.full_redraw()

    def _get_visible_prefix_len(self, msg_type, alias):
        """Calculates the exact length of the prefix without invisible color codes."""
        prompt_len = len(self._initial_prompt)
        if msg_type == "info": return 4 + prompt_len 
        if msg_type == "system": return 6 + prompt_len 
        if msg_type == "raw": return 0
        if msg_type == "self":
            return len(f"To {alias}") + prompt_len if alias else 4 + prompt_len
        if msg_type == "remote":
            return len(f"From {alias}") + prompt_len if alias else 6 + prompt_len
        return 0

    def _format_msg(self, msg_dict):
        msg_type = msg_dict["msg_type"]
        alias = msg_dict["alias"]
        text = msg_dict["text"]
        is_pending = msg_dict["is_pending"]

        if alias and "{alias}" in text:
            text = text.replace("{alias}", alias)

        prefix = ""
        if msg_type == "info": 
            prefix = f"{Settings.YELLOW}info{self._initial_prompt}{Settings.RESET}"
        elif msg_type == "system": 
            prefix = f"{Settings.CYAN}system{self._initial_prompt}{Settings.RESET}"
        elif msg_type != "raw":
            is_focused = (alias == self._current_focus) if alias else False
            if not is_focused:
                prefix_raw = f"To {alias}{self._initial_prompt}" if (msg_type == "self" and alias) else \
                             f"self{self._initial_prompt}" if msg_type == "self" else \
                             f"From {alias}{self._initial_prompt}" if alias else f"remote{self._initial_prompt}"
                prefix = f"{Settings.DARK_GREY}{prefix_raw}{Settings.RESET}"
            elif msg_type == "self":
                prefix_raw = f"To {alias}{self._initial_prompt}" if alias else f"self{self._initial_prompt}"
                prefix = f"{prefix_raw}" if is_pending else f"{Settings.GREEN}{prefix_raw}{Settings.RESET}"
            elif msg_type == "remote":
                prefix_raw = f"From {alias}{self._initial_prompt}" if alias else f"remote{self._initial_prompt}"
                prefix = f"{Settings.PURPLE}{prefix_raw}{Settings.RESET}"

        if "\n" in text and msg_type != "raw":
            pad_len = self._get_visible_prefix_len(msg_type, alias)
            padding = " " * pad_len
            lines = text.split("\n")
            text = f"\n{padding}".join(lines)

        return f"{prefix}{text}"

    def _get_visual_lines(self, msg_dict, cols):
        """Calculates exactly how many terminal lines a message will occupy due to line wrapping."""
        msg_type = msg_dict.get("msg_type", "raw")
        alias = msg_dict.get("alias")
        text = msg_dict.get("text", "")
        
        if alias and "{alias}" in text:
            text = text.replace("{alias}", alias)
            
        clean_text = self._ansi_escape.sub('', text)
        prefix_len = self._get_visible_prefix_len(msg_type, alias)
        
        lines = clean_text.split('\n')
        count = 0
        for l in lines:
            count += max(1, (prefix_len + len(l) + cols - 1) // cols)
        return count

    def _get_input_visual_lines(self, cols):
        lines = self._current_input.split('\n')
        count = 0
        for l in lines:
            offset = len(self._prompt) 
            count += max(1, (offset + len(l) + cols - 1) // cols)
        return count

    def _clear_input_area_locked(self, cols):
        """Clears the input area dynamically, regardless of how many line breaks it has."""
        if self._last_visual_lines > 1:
            sys.stdout.write(f"\033[{self._last_visual_lines - 1}A")
        sys.stdout.write("\r\033[J")

    def _print_prompt_and_input(self, cols, input_lines):
        """Prints the prompt and restores the cursor to the exact character."""
        sys.stdout.write(self._prompt)
        
        padding = " " * len(self._prompt)
        display_input = self._current_input.replace("\n", "\n" + padding)
        sys.stdout.write(display_input)
        
        text_to_cursor = ''.join(self._line_chars[:self._cursor_index])
        cursor_lines = 0
        lines = text_to_cursor.split('\n')
        
        for l in lines:
            offset = len(self._prompt)
            cursor_lines += max(1, (offset + len(l) + cols - 1) // cols)
            
        lines_up = input_lines - cursor_lines
        cursor_part = lines[-1]
        
        col_pos = (len(self._prompt) + len(cursor_part)) % cols
            
        if lines_up > 0: sys.stdout.write(f"\033[{lines_up}A")
        sys.stdout.write(f"\r\033[{col_pos}C" if col_pos > 0 else "\r")
        sys.stdout.flush()

    def print_message(self, msg, msg_type=None, alias=None, skip_prompt=False, msg_id=None):
        with self._print_lock:
            cols = shutil.get_terminal_size().columns
            if cols < 1: cols = 80
            
            self._clear_input_area_locked(cols)
            
            msg_dict = {
                "text": str(msg),
                "msg_type": msg_type or "raw",
                "alias": alias,
                "is_pending": bool(msg_id),
                "msg_id": msg_id
            }
            self._all_msgs.append(msg_dict)
            formatted_msg = self._format_msg(msg_dict)
            sys.stdout.write(formatted_msg + "\n")
                
            if not skip_prompt:
                self._last_visual_lines = self._get_input_visual_lines(cols)
                self._print_prompt_and_input(cols, self._last_visual_lines)
            else:
                self._last_visual_lines = 1
                
            sys.stdout.flush()

    def mark_acked(self, msg_id):
        start_idx = -1
        for i, msg in enumerate(self._all_msgs):
            if msg.get("msg_id") == msg_id:
                msg["is_pending"] = False
                if start_idx == -1: start_idx = i
                
        if start_idx != -1:
            self._redraw_from_index(start_idx)

    def rename_alias_in_history(self, old_alias, new_alias):
        start_idx = -1
        for i, msg in enumerate(self._all_msgs):
            if msg.get("alias") == old_alias:
                msg["alias"] = new_alias
                if start_idx == -1: start_idx = i
                
        if start_idx != -1:
            self._redraw_from_index(start_idx)

    def _redraw_from_index(self, start_idx):
        """Clears and redraws only the changed part of the screen (Soft Redraw)."""
        with self._print_lock:
            cols = shutil.get_terminal_size().columns
            if cols < 1: cols = 80
            
            self._clear_input_area_locked(cols)
            
            lines_to_go_up = 0
            for i in range(start_idx, len(self._all_msgs)):
                lines_to_go_up += self._get_visual_lines(self._all_msgs[i], cols)
                
            term_height = shutil.get_terminal_size().lines
            if lines_to_go_up >= term_height:
                self._full_redraw_locked(cols)
                return

            if lines_to_go_up > 0:
                sys.stdout.write(f"\033[{lines_to_go_up}A\r\033[J")
                
            for i in range(start_idx, len(self._all_msgs)):
                formatted_msg = self._format_msg(self._all_msgs[i])
                sys.stdout.write(formatted_msg + "\n")
                
            self._last_visual_lines = self._get_input_visual_lines(cols)
            self._print_prompt_and_input(cols, self._last_visual_lines)

    def print_prompt(self):
        sys.stdout.write(self._prompt)
        sys.stdout.flush()

    def print_empty_line(self):
        self.print_message(" ", msg_type="raw", skip_prompt=True)
    
    def print_divider(self, msg_type=None):
        self.print_message("---------------------------------", msg_type=msg_type)

    def clear_line(self):
        with self._print_lock:
            cols = shutil.get_terminal_size().columns
            if cols < 1: cols = 80
            self._clear_input_area_locked(cols)
            sys.stdout.flush()

    def clear_input_area(self):
        self.clear_line()

    def clear_screen(self):
        with self._print_lock:
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()
            self._all_msgs = []

    def _on_resize(self, _signum, _frame):
        if self._is_redrawing: return
        current_cols = shutil.get_terminal_size().columns
        if current_cols == self._last_cols: return
        self._last_cols = current_cols
        self._is_redrawing = True
        try: self.full_redraw()
        finally: self._is_redrawing = False

    def full_redraw(self):
        with self._print_lock:
            cols = shutil.get_terminal_size().columns
            if cols < 1: cols = 80
            self._full_redraw_locked(cols)

    def _full_redraw_locked(self, cols):
        sys.stdout.write("\033[2J\033[H")
        for msg_dict in self._all_msgs:
            formatted_msg = self._format_msg(msg_dict)
            sys.stdout.write(formatted_msg + "\n")
            
        self._last_visual_lines = self._get_input_visual_lines(cols)
        self._print_prompt_and_input(cols, self._last_visual_lines)
        sys.stdout.flush()

    def start_loading(self, msg="...", show_prompt=False):
        if show_prompt: self.print_prompt()
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
                if ch == "\x0e": return "SPECIAL:NEWLINE" 
                return ch
            return None
        else:
            # Blocks correctly to ensure escape sequences are kept whole
            ch1 = sys.stdin.read(1)
            if ch1 == '\x1b':
                ch2 = sys.stdin.read(1)
                if ch2 == '[':
                    ch3 = sys.stdin.read(1)
                    return {'A': 'SPECIAL:UP', 'B': 'SPECIAL:DOWN', 'C': 'SPECIAL:RIGHT', 'D': 'SPECIAL:LEFT'}.get(ch3, 'SPECIAL:UNKNOWN')
                if ch2 in ('\n', '\r'): return "SPECIAL:NEWLINE" 
                return 'ESC'
            if ch1 == '\x0e': return "SPECIAL:NEWLINE" 
            return ch1

    def read_line(self):
        with self._print_lock:
            self._line_chars = []
            self._cursor_index = 0
            self._current_input = ""
            self._last_visual_lines = 1
            
        while True:
            ch = self._get_char()
            if ch is None:
                time.sleep(0.02)
                continue

            with self._print_lock:
                cols = shutil.get_terminal_size().columns
                if cols < 1: cols = 80

                if ch.startswith("SPECIAL:"):
                    key = ch.split(":")[1]
                    if key == "UP":
                        if self._input_history and self._history_index < len(self._input_history) - 1:
                            self._history_index += 1
                            new_line = self._input_history[-(self._history_index + 1)]
                        else:
                            new_line = self._input_history[0] if self._input_history else ""
                        self._line_chars = list(new_line)
                        self._cursor_index = len(self._line_chars)
                    elif key == "DOWN":
                        if self._history_index > 0:
                            self._history_index -= 1
                            new_line = self._input_history[-(self._history_index + 1)]
                        else:
                            self._history_index = -1
                            new_line = ""
                        self._line_chars = list(new_line)
                        self._cursor_index = len(self._line_chars)
                    elif key == "LEFT":
                        if self._cursor_index > 0: self._cursor_index -= 1
                    elif key == "RIGHT":
                        if self._cursor_index < len(self._line_chars): self._cursor_index += 1
                    elif key == "NEWLINE":
                        self._line_chars.insert(self._cursor_index, '\n')
                        self._cursor_index += 1
                        
                elif ch in ("\n", "\r"):
                    self._clear_input_area_locked(cols)
                    line = ''.join(self._line_chars)
                    if line.strip(): self._input_history.append(line)
                    self._history_index = -1
                    self._current_input = ""
                    self._line_chars = []
                    self._cursor_index = 0
                    self._last_visual_lines = 1
                    sys.stdout.flush()
                    return line
                    
                elif ch in ("\b", "\x7f"):
                    if self._cursor_index > 0:
                        del self._line_chars[self._cursor_index - 1]
                        self._cursor_index -= 1
                else:
                    self._line_chars.insert(self._cursor_index, ch)
                    self._cursor_index += 1
                    
                self._current_input = ''.join(self._line_chars)
                self._clear_input_area_locked(cols)
                self._last_visual_lines = self._get_input_visual_lines(cols)
                self._print_prompt_and_input(cols, self._last_visual_lines)
