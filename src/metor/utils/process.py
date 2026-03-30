"""
Module for managing OS-level processes and cleanup operations.
Isolates external dependencies like psutil from the core domain logic.
"""

import psutil


class ProcessManager:
    """Manages OS-level process discovery and termination."""

    @staticmethod
    def cleanup_processes() -> int:
        """
        Kills all active Tor processes.

        Args:
            None

        Returns:
            int: The number of processes successfully killed.
        """
        killed: int = 0
        for proc in psutil.process_iter(['pid', 'name', 'status']):
            try:
                if proc.info.get('status') == psutil.STATUS_ZOMBIE:
                    continue
                proc_name: str = proc.info['name'].lower() if proc.info['name'] else ''
                if proc_name in ('tor', 'tor.exe'):
                    proc.kill()
                    killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

        return killed
