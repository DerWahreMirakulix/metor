"""
Module for managing OS-level processes and cleanup operations.
Isolates external dependencies like psutil from the core domain logic.
"""

import psutil
from pathlib import Path

# Local Package Imports
from metor.utils.constants import Constants


class ProcessManager:
    """Manages OS-level process discovery and termination."""

    @staticmethod
    def cleanup_processes() -> int:
        """
        Kills all active Tor processes by reading explicit PID files from profiles.
        Prevents killing unrelated Tor instances (like Tor Browser).

        Args:
            None

        Returns:
            int: The number of processes successfully killed.
        """
        killed: int = 0
        if not Constants.DATA.exists():
            return killed

        for profile_dir in Constants.DATA.iterdir():
            if not profile_dir.is_dir() or profile_dir.name in (
                Constants.HIDDEN_SERVICE_DIR,
                Constants.TOR_DATA_DIR,
            ):
                continue

            pid_file: Path = profile_dir / Constants.TOR_DATA_DIR / 'tor.pid'
            if pid_file.exists():
                try:
                    with pid_file.open('r') as f:
                        pid_str: str = f.read().strip()

                    if pid_str.isdigit():
                        pid: int = int(pid_str)
                        if psutil.pid_exists(pid):
                            proc = psutil.Process(pid)
                            proc_name: str = proc.name().lower()
                            if proc_name in ('tor', 'tor.exe'):
                                proc.kill()
                                killed += 1
                except (OSError, ValueError, psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                finally:
                    pid_file.unlink(missing_ok=True)

        return killed
