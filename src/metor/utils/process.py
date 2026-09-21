"""
Module for managing OS-level processes and cleanup operations.
Isolates external dependencies like psutil from the core domain logic.
"""

import os
import logging
import re
import stat
from dataclasses import dataclass
from functools import partial
from typing import Callable, Optional, Set

import psutil
from pathlib import Path

# Local Package Imports
from metor.utils.constants import Constants


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ProcessIdentity:
    """Persisted process lifetime and profile ownership."""

    pid: int
    create_time: float
    profile_name: str


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
            pid_text = pid_str.split(':', 1)[0]
            return int(pid_text) if pid_text.isdigit() else None
        except OSError:
            return None

    @staticmethod
    def process_identity_payload(pid: int, profile_name: str) -> str:
        """Builds persisted identity for one process owned by a profile.

        Args:
            pid (int): Process identifier.
            profile_name (str): Exact owning profile identity.

        Returns:
            str: PID, creation time, and profile metadata.

        Raises:
            psutil.Error: If the process lifetime cannot be inspected.
        """
        create_time = psutil.Process(pid).create_time()
        return f'{pid}:{create_time}:{profile_name}'

    @staticmethod
    def _read_process_identity(file_path: Path) -> Optional[_ProcessIdentity]:
        """Reads strict lifetime-bound process ownership metadata.

        Args:
            file_path (Path): Managed PID metadata file.

        Returns:
            Optional[_ProcessIdentity]: Parsed identity, or None when untrusted.
        """
        try:
            pid_text, created_text, profile_name = (
                file_path.read_text().strip().split(':', 2)
            )
            if not pid_text.isdigit() or not profile_name:
                return None
            return _ProcessIdentity(
                int(pid_text),
                float(created_text),
                profile_name,
            )
        except (OSError, ValueError):
            return None

    @staticmethod
    def is_pid_running(pid: int) -> Optional[bool]:
        """
        Checks whether one process ID still belongs to a live OS process.

        Args:
            pid (int): The process identifier.

        Returns:
            Optional[bool]: True if alive, False if confirmed absent, or None if
                process ownership cannot be inspected.
        """
        try:
            proc = psutil.Process(pid)
            is_running: bool = bool(proc.is_running())
            status: str = str(proc.status())
            return is_running and status != str(psutil.STATUS_ZOMBIE)
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            return False
        except psutil.AccessDenied:
            return None

    @staticmethod
    def is_managed_process_running(
        pid_file: Path,
        profile_name: str,
    ) -> Optional[bool]:
        """Checks runtime state against persisted lifetime and profile ownership.

        Args:
            pid_file (Path): Managed process identity file.
            profile_name (str): Expected owning profile.

        Returns:
            Optional[bool]: True for the recorded live process, False when the
                recorded generation is gone, or None when identity is unknown.
        """
        identity = ProcessManager._read_process_identity(pid_file)
        if identity is None:
            legacy_pid = ProcessManager._read_pid_file(pid_file)
            return (
                ProcessManager.is_pid_running(legacy_pid)
                if legacy_pid is not None
                else None
            )
        if identity.profile_name != profile_name:
            return None
        try:
            proc = psutil.Process(identity.pid)
            if abs(proc.create_time() - identity.create_time) >= 0.01:
                return False
            if ProcessManager._same_os_owner(proc) is not True:
                return None
            return bool(
                proc.is_running() and str(proc.status()) != str(psutil.STATUS_ZOMBIE)
            )
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            return False
        except psutil.AccessDenied:
            return None

    @staticmethod
    def _same_os_owner(proc: psutil.Process) -> Optional[bool]:
        """Checks whether a candidate belongs to the current OS account.

        Args:
            proc (psutil.Process): Candidate managed process.

        Returns:
            Optional[bool]: Ownership match, mismatch, or unknown.
        """
        try:
            if os.name != 'nt' and hasattr(os, 'getuid'):
                return bool(proc.uids().real == os.getuid())
            current_user = psutil.Process(os.getpid()).username()
            return bool(proc.username() == current_user)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return None

    @staticmethod
    def _is_tor_process(proc: psutil.Process, profile_dir: Path) -> bool:
        """
        Verifies that one PID belongs to a Tor process owned by Metor.

        Args:
            proc (psutil.Process): The candidate process.
            profile_dir (Path): Expected owning profile directory.

        Returns:
            bool: True if the process looks like Tor.
        """
        try:
            if proc.name().lower() not in ('tor', 'tor.exe'):
                return False
            cmdline = proc.cmdline()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False

        def option_value(option: str) -> Optional[str]:
            for index, value in enumerate(cmdline):
                if value == option and index + 1 < len(cmdline):
                    return str(cmdline[index + 1])
                if value.startswith(f'{option}='):
                    return str(value.split('=', 1)[1])
            return None

        return option_value('--DataDirectory') == str(
            profile_dir / Constants.TOR_DATA_DIR
        ) and option_value('--HiddenServiceDir') == str(
            profile_dir / Constants.HIDDEN_SERVICE_DIR
        )

    @staticmethod
    def _is_metor_daemon_process(
        proc: psutil.Process,
        profile_name: str,
        *,
        require_explicit_profile: bool = False,
    ) -> bool:
        """
        Verifies that one PID belongs to a Metor daemon process.

        Args:
            proc (psutil.Process): The candidate process.
            profile_name (str): Expected owning profile identity.
            require_explicit_profile (bool): Whether argv must name the profile.

        Returns:
            bool: True if the process command line matches Metor daemon startup.
        """
        try:
            cmdline = proc.cmdline()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False

        if not cmdline:
            return False

        executable = Path(cmdline[0]).name.lower()
        arguments = cmdline[1:]
        python_executable = re.fullmatch(
            r'python(?:3(?:\.\d+)*)?(?:\.exe)?',
            executable,
        )
        internal = python_executable is not None and arguments[:2] == [
            '-m',
            'metor.daemon_main',
        ]
        public = executable in ('metor', 'metor.exe')
        headless_alias = executable in ('metor-daemon', 'metor-daemon.exe')
        if internal:
            arguments = arguments[2:]
        elif not public and not headless_alias:
            return False

        explicit_profile = False
        daemon_count = 0
        index = 0
        allowed_flags = {'--locked'}
        if internal or headless_alias:
            allowed_flags.add('--startup-session-auth-stdin')
        while index < len(arguments):
            argument = arguments[index]
            if argument == 'daemon':
                daemon_count += 1
            elif argument in allowed_flags:
                pass
            if argument in ('-p', '--profile'):
                if index + 1 >= len(arguments) or arguments[index + 1] != profile_name:
                    return False
                explicit_profile = True
                index += 1
            elif argument.startswith('--profile='):
                if argument.split('=', 1)[1] != profile_name:
                    return False
                explicit_profile = True
            elif argument != 'daemon' and argument not in allowed_flags:
                return False
            index += 1

        valid_command = daemon_count == 1 or (headless_alias and daemon_count == 0)
        return valid_command and (
            explicit_profile
            or ((public or headless_alias) and not require_explicit_profile)
        )

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
        profile_name: str,
        validator: Callable[[psutil.Process], bool],
    ) -> int:
        """
        Terminates one managed process referenced by a PID file.

        Args:
            pid_file (Path): The PID file to inspect.
            profile_name (str): Expected owning profile identity.
            validator (Callable[[psutil.Process], bool]): Validates process role.

        Returns:
            int: 1 if a managed process was terminated, otherwise 0.
        """
        if not pid_file.exists():
            return 0

        identity = ProcessManager._read_process_identity(pid_file)
        if identity is None or identity.profile_name != profile_name:
            logger.warning(
                'Skipping process cleanup with untrusted PID metadata: %s', pid_file
            )
            return 0

        killed: int = 0
        should_remove_pid_file: bool = False
        try:
            proc = psutil.Process(identity.pid)
            if abs(proc.create_time() - identity.create_time) >= 0.01:
                logger.warning('Skipping cleanup for a reused PID: %s', identity.pid)
                return 0
            if ProcessManager._same_os_owner(proc) is not True:
                logger.warning(
                    'Skipping cleanup with unknown or foreign owner: %s', identity.pid
                )
                return 0
            if not validator(proc):
                logger.warning(
                    'Skipping cleanup for an unrecognized process: %s', identity.pid
                )
                return 0

            if ProcessManager._terminate_process(proc):
                killed = 1
                should_remove_pid_file = True
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            should_remove_pid_file = True
        except (OSError, ValueError, psutil.AccessDenied) as exc:
            logger.warning('Process cleanup ownership check failed: %s', exc)
        finally:
            if should_remove_pid_file:
                pid_file.unlink(missing_ok=True)

        return killed

    @staticmethod
    def _is_owned_profile_directory(profile_dir: Path) -> bool:
        """Checks one direct data child without following link aliases.

        Args:
            profile_dir (Path): Candidate profile directory.

        Returns:
            bool: Whether the path is an ordinary non-reparse directory.
        """
        try:
            path_info = profile_dir.lstat()
        except OSError:
            return False
        file_attributes = getattr(path_info, 'st_file_attributes', 0)
        return (
            stat.S_ISDIR(path_info.st_mode)
            and not stat.S_ISLNK(path_info.st_mode)
            and not file_attributes & 0x00000400
        )

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

                if ProcessManager._same_os_owner(proc) is not True:
                    continue
                matched_profile = any(
                    ProcessManager._is_owned_profile_directory(profile_dir)
                    and ProcessManager._is_metor_daemon_process(
                        proc,
                        profile_dir.name,
                        require_explicit_profile=True,
                    )
                    for profile_dir in Constants.DATA.iterdir()
                )
                if matched_profile and ProcessManager._terminate_process(proc):
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
                if not ProcessManager._is_owned_profile_directory(
                    profile_dir
                ) or profile_dir.name in (
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
                    profile_dir.name,
                    partial(
                        ProcessManager._is_metor_daemon_process,
                        profile_name=profile_dir.name,
                    ),
                )

                pid_file: Path = profile_dir / Constants.TOR_DATA_DIR / 'tor.pid'
                killed += ProcessManager._cleanup_pid_file_process(
                    pid_file,
                    profile_dir.name,
                    partial(
                        ProcessManager._is_tor_process,
                        profile_dir=profile_dir,
                    ),
                )

        if force:
            killed += ProcessManager._cleanup_untracked_daemons_force(
                handled_daemon_pids
            )

        return killed
