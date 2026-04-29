"""
Module for managing OS-level processes and cleanup operations.
Isolates external dependencies like psutil from the core domain logic.
"""

import os
from typing import Callable, Optional, Set

import psutil
from pathlib import Path

# Local Package Imports
from metor.utils.constants import Constants


class ProcessManager:
    """Manages OS-level process discovery and termination."""

    @staticmethod
    def _read_pid_file(file_path: Path) -> Optional[int]:
        """
        Reads one PID from disk when the file contains a valid integer.

        Args:
            file_path (Path): The PID file to inspect.

        Returns:
            Optional[int]: The parsed PID, or None if unavailable.
        """
        if not file_path.exists():
            return None

        try:
            with file_path.open('r') as f:
                pid_str: str = f.read().strip()
            return int(pid_str) if pid_str.isdigit() else None
        except OSError:
            return None

    @staticmethod
    def is_pid_running(pid: int) -> bool:
        """
        Checks whether one process ID still belongs to a live OS process.

        Args:
            pid (int): The process identifier.

        Returns:
            bool: True if the process is alive and not a zombie.
        """
        try:
            proc = psutil.Process(pid)
            is_running: bool = bool(proc.is_running())
            status: str = str(proc.status())
            return is_running and status != str(psutil.STATUS_ZOMBIE)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False

    @staticmethod
    def _is_tor_process(proc: psutil.Process) -> bool:
        """
        Verifies that one PID belongs to a Tor process owned by Metor.

        Args:
            proc (psutil.Process): The candidate process.

        Returns:
            bool: True if the process looks like Tor.
        """
        try:
            return proc.name().lower() in ('tor', 'tor.exe')
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False

    @staticmethod
    def _is_metor_daemon_process(proc: psutil.Process) -> bool:
        """
        Verifies that one PID belongs to a Metor daemon process.

        Args:
            proc (psutil.Process): The candidate process.

        Returns:
            bool: True if the process command line matches Metor daemon startup.
        """
        try:
            cmdline = [part.lower() for part in proc.cmdline()]
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False

        if not cmdline or 'daemon' not in cmdline:
            return False

        return any('metor' in part for part in cmdline)

    @staticmethod
    def _terminate_process(proc: psutil.Process) -> bool:
        """
        Terminates one managed process and waits briefly for exit.

        Args:
            proc (psutil.Process): The managed process.

        Returns:
            bool: True if the process was terminated or already gone.
        """
        try:
            proc.terminate()
            proc.wait(timeout=Constants.TOR_KILL_TIMEOUT_SEC)
            return True
        except psutil.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=Constants.TOR_KILL_TIMEOUT_SEC)
                return True
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                return True
            except (
                psutil.AccessDenied,
                psutil.TimeoutExpired,
            ):
                return False
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            return True
        except psutil.AccessDenied:
            return False

    @staticmethod
    def _cleanup_pid_file_process(
        pid_file: Path,
        validator: Callable[[psutil.Process], bool],
    ) -> int:
        """
        Terminates one managed process referenced by a PID file.

        Args:
            pid_file (Path): The PID file to inspect.
            validator (Callable[[psutil.Process], bool]): Validates the target process type.

        Returns:
            int: 1 if a managed process was terminated, otherwise 0.
        """
        if not pid_file.exists():
            return 0

        killed: int = 0
        should_remove_pid_file: bool = False
        try:
            with pid_file.open('r') as f:
                pid_str: str = f.read().strip()

            if not pid_str.isdigit():
                return 0

            pid: int = int(pid_str)
            if not ProcessManager.is_pid_running(pid):
                should_remove_pid_file = True
                return 0

            proc = psutil.Process(pid)
            if not validator(proc):
                return 0

            if ProcessManager._terminate_process(proc):
                killed = 1
                should_remove_pid_file = True
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            should_remove_pid_file = True
        except (OSError, ValueError, psutil.AccessDenied):
            pass
        finally:
            if should_remove_pid_file:
                pid_file.unlink(missing_ok=True)

        return killed

    @staticmethod
    def _cleanup_untracked_daemons_force(excluded_pids: Set[int]) -> int:
        """
        Force-scans the current user's processes for Metor daemons when local runtime-state files are missing or corrupted.

        Args:
            excluded_pids (Set[int]): PIDs already handled through explicit state files.

        Returns:
            int: The number of extra daemon processes terminated.
        """
        killed: int = 0
        current_uid: Optional[int] = os.getuid() if hasattr(os, 'getuid') else None

        for proc in psutil.process_iter():
            try:
                if proc.pid in excluded_pids:
                    continue

                if current_uid is not None and proc.uids().real != current_uid:
                    continue

                if not ProcessManager._is_metor_daemon_process(proc):
                    continue

                if ProcessManager._terminate_process(proc):
                    killed += 1
            except (
                OSError,
                psutil.NoSuchProcess,
                psutil.AccessDenied,
                psutil.ZombieProcess,
            ):
                continue

        return killed

    @staticmethod
    def cleanup_processes(force: bool = False) -> int:
        """
        Kills managed Metor daemon and Tor processes by reading explicit PID files.
        Prevents killing unrelated system processes by validating each target first.

        Args:
            force (bool): Enables an explicit rescue scan for untracked local Metor daemons.

        Returns:
            int: The number of processes successfully killed.
        """
        killed: int = 0
        handled_daemon_pids: Set[int] = set()

        if Constants.DATA.exists():
            for profile_dir in Constants.DATA.iterdir():
                if not profile_dir.is_dir() or profile_dir.name in (
                    Constants.HIDDEN_SERVICE_DIR,
                    Constants.TOR_DATA_DIR,
                ):
                    continue

                daemon_pid_file: Path = profile_dir / Constants.DAEMON_PID_FILE
                daemon_pid: Optional[int] = ProcessManager._read_pid_file(
                    daemon_pid_file
                )
                if daemon_pid is not None:
                    handled_daemon_pids.add(daemon_pid)

                killed += ProcessManager._cleanup_pid_file_process(
                    daemon_pid_file,
                    ProcessManager._is_metor_daemon_process,
                )

                pid_file: Path = profile_dir / Constants.TOR_DATA_DIR / 'tor.pid'
                killed += ProcessManager._cleanup_pid_file_process(
                    pid_file,
                    ProcessManager._is_tor_process,
                )

        if force:
            killed += ProcessManager._cleanup_untracked_daemons_force(
                handled_daemon_pids
            )

        return killed
