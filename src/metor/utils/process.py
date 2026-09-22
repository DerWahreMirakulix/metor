"""
Module for managing OS-level processes and cleanup operations.
Isolates external dependencies like psutil from the core domain logic.
"""

import errno
import json
import logging
import math
import os
import stat
import sys
import sysconfig
from dataclasses import dataclass
from typing import Callable, Optional

import psutil
from pathlib import Path

# Local Package Imports
from metor.utils.constants import Constants


logger = logging.getLogger(__name__)


def _current_posix_uid() -> int:
    """Returns the POSIX owner without assuming that Windows exports getuid.

    Args:
        None

    Returns:
        int: Numeric user identifier for the current POSIX process.

    Raises:
        OSError: If the runtime does not expose POSIX ownership information.
    """
    get_uid = getattr(os, 'getuid', None)
    if get_uid is None:
        raise OSError(errno.ENOTSUP, 'POSIX owner validation is unavailable.')
    return int(get_uid())


@dataclass(frozen=True)
class _ProcessIdentity:
    """Persisted process lifetime and profile ownership."""

    pid: int
    create_time: float
    profile_name: str
    role: str
    executable: str
    installation_root: str


class ProcessManager:
    """Manages OS-level process discovery and termination."""

    @staticmethod
    def _installation_root() -> Path:
        """Returns the exact package root for the running Metor installation.

        Args:
            None

        Returns:
            Path: Resolved directory containing the installed ``metor`` package.
        """
        return Path(__file__).resolve().parents[2]

    @staticmethod
    def process_identity_payload(
        pid: int,
        profile_name: str,
        *,
        role: str,
        executable: Path,
    ) -> str:
        """Builds persisted identity for one process owned by a profile.

        Args:
            pid (int): Process identifier.
            profile_name (str): Exact owning profile identity.
            role (str): Managed process role.
            executable (Path): Exact executable selected by the owner.

        Returns:
            str: PID, creation time, and profile metadata.

        Raises:
            psutil.Error: If the process lifetime cannot be inspected.
        """
        create_time: float = float(psutil.Process(pid).create_time())
        if pid <= 0 or not math.isfinite(create_time) or create_time <= 0:
            raise ValueError('Managed process lifetime metadata is invalid.')
        if role not in (Constants.PROCESS_ROLE_DAEMON, Constants.PROCESS_ROLE_TOR):
            raise ValueError('Managed process role is invalid.')
        return json.dumps(
            {
                'create_time': create_time,
                'executable': str(executable.resolve()),
                'installation_root': str(ProcessManager._installation_root()),
                'pid': pid,
                'profile': profile_name,
                'role': role,
            },
            separators=(',', ':'),
            sort_keys=True,
        )

    @staticmethod
    def _read_process_identity(file_path: Path) -> Optional[_ProcessIdentity]:
        """Reads strict lifetime-bound process ownership metadata.

        Args:
            file_path (Path): Managed PID metadata file.

        Returns:
            Optional[_ProcessIdentity]: Parsed identity, or None when untrusted.
        """
        flags: int = os.O_RDONLY
        flags |= int(getattr(os, 'O_CLOEXEC', 0))
        flags |= int(getattr(os, 'O_NOFOLLOW', 0))
        flags |= int(getattr(os, 'O_NONBLOCK', 0))
        try:
            descriptor: int = os.open(file_path, flags)
            try:
                info = os.fstat(descriptor)
                file_attributes: int = int(getattr(info, 'st_file_attributes', 0))
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1
                    or file_attributes & 0x00000400
                    or info.st_size > Constants.PROCESS_IDENTITY_MAX_BYTES
                ):
                    os.close(descriptor)
                    return None
                if os.name != 'nt' and (
                    info.st_uid != _current_posix_uid() or info.st_mode & 0o077
                ):
                    os.close(descriptor)
                    return None
                with os.fdopen(descriptor, 'rb') as handle:
                    raw_payload: bytes = handle.read(
                        Constants.PROCESS_IDENTITY_MAX_BYTES + 1
                    )
            except BaseException:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                raise
            if len(raw_payload) > Constants.PROCESS_IDENTITY_MAX_BYTES:
                return None
            payload = json.loads(raw_payload.decode('utf-8'))
            if type(payload) is not dict or set(payload) != {
                'create_time',
                'executable',
                'installation_root',
                'pid',
                'profile',
                'role',
            }:
                return None
            pid = payload['pid']
            create_time = payload['create_time']
            profile_name = payload['profile']
            role = payload['role']
            executable = payload['executable']
            installation_root = payload['installation_root']
            if (
                type(pid) is not int
                or pid <= 0
                or type(create_time) not in (int, float)
                or not math.isfinite(float(create_time))
                or float(create_time) <= 0
                or type(profile_name) is not str
                or not profile_name
                or type(role) is not str
                or role
                not in (Constants.PROCESS_ROLE_DAEMON, Constants.PROCESS_ROLE_TOR)
                or type(executable) is not str
                or not executable
                or type(installation_root) is not str
                or not installation_root
            ):
                return None
            return _ProcessIdentity(
                pid=pid,
                create_time=float(create_time),
                profile_name=profile_name,
                role=role,
                executable=executable,
                installation_root=installation_root,
            )
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
            return None

    @staticmethod
    def managed_process_pid(
        file_path: Path,
        profile_name: str,
        role: str,
    ) -> Optional[int]:
        """Returns a PID only from exact trusted managed-process metadata.

        Args:
            file_path (Path): Managed identity file.
            profile_name (str): Expected owning profile.
            role (str): Expected managed process role.

        Returns:
            Optional[int]: Bound PID, or None when metadata is untrusted.
        """
        identity = ProcessManager._read_process_identity(file_path)
        if (
            identity is None
            or identity.profile_name != profile_name
            or identity.role != role
            or identity.installation_root != str(ProcessManager._installation_root())
        ):
            return None
        return identity.pid

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
            return None
        if (
            identity.profile_name != profile_name
            or identity.role != Constants.PROCESS_ROLE_DAEMON
            or identity.installation_root != str(ProcessManager._installation_root())
            or identity.executable != str(Path(sys.executable).resolve())
        ):
            return None
        try:
            proc = psutil.Process(identity.pid)
            if (
                abs(proc.create_time() - identity.create_time)
                >= Constants.PROCESS_CREATE_TIME_TOLERANCE_SEC
            ):
                return False
            if ProcessManager._same_os_owner(proc) is not True:
                return None
            if not ProcessManager._is_metor_daemon_process(
                proc,
                profile_name,
                identity=identity,
            ):
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
            if os.name != 'nt':
                return bool(proc.uids().real == _current_posix_uid())
            current_user = psutil.Process(os.getpid()).username()
            return bool(proc.username() == current_user)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return None

    @staticmethod
    def _is_tor_process(
        proc: psutil.Process,
        profile_dir: Path,
        *,
        identity: Optional[_ProcessIdentity] = None,
    ) -> bool:
        """
        Verifies that one PID belongs to a Tor process owned by Metor.

        Args:
            proc (psutil.Process): The candidate process.
            profile_dir (Path): Expected owning profile directory.
            identity (Optional[_ProcessIdentity]): Persisted owner-created process identity.

        Returns:
            bool: True if the process looks like Tor.
        """
        try:
            if identity is None:
                return False
            if (
                identity.role != Constants.PROCESS_ROLE_TOR
                or identity.profile_name != profile_dir.name
                or identity.installation_root
                != str(ProcessManager._installation_root())
            ):
                return False
            executable = Path(proc.exe()).resolve()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False
        except OSError:
            return False
        return str(executable) == identity.executable

    @staticmethod
    def _is_metor_daemon_process(
        proc: psutil.Process,
        profile_name: str,
        *,
        require_explicit_profile: bool = False,
        identity: Optional[_ProcessIdentity] = None,
    ) -> bool:
        """
        Verifies that one PID belongs to a Metor daemon process.

        Args:
            proc (psutil.Process): The candidate process.
            profile_name (str): Expected owning profile identity.
            require_explicit_profile (bool): Whether argv must name the profile.
            identity (Optional[_ProcessIdentity]): Persisted owner-created process identity, when available.

        Returns:
            bool: True if the process command line matches Metor daemon startup.
        """
        try:
            cmdline = proc.cmdline()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False

        if not cmdline:
            return False

        current_interpreter: Path = Path(sys.executable).resolve()
        scripts_value: Optional[str] = sysconfig.get_path('scripts')
        if scripts_value is None:
            return False
        launcher_name: str = 'metor.exe' if os.name == 'nt' else 'metor'
        expected_launcher: Path = Path(scripts_value).resolve() / launcher_name
        try:
            argv_zero: Path = Path(cmdline[0]).resolve()
        except OSError:
            return False

        arguments: list[str]
        if argv_zero == current_interpreter and cmdline[1:3] == ['-m', 'metor']:
            arguments = cmdline[3:]
        elif (
            argv_zero == current_interpreter
            and len(cmdline) >= 2
            and Path(cmdline[1]).resolve() == expected_launcher
        ):
            arguments = cmdline[2:]
        elif os.name == 'nt' and argv_zero == expected_launcher:
            arguments = cmdline[1:]
        else:
            return False

        if identity is not None and (
            identity.role != Constants.PROCESS_ROLE_DAEMON
            or identity.profile_name != profile_name
            or identity.executable != str(current_interpreter)
            or identity.installation_root != str(ProcessManager._installation_root())
        ):
            return False

        return ProcessManager._daemon_arguments_match(
            arguments,
            profile_name,
            require_explicit_profile=require_explicit_profile,
        )

    @staticmethod
    def _daemon_arguments_match(
        arguments: list[str],
        profile_name: str,
        *,
        require_explicit_profile: bool,
    ) -> bool:
        """Validates the narrow argument forms that can own a daemon PID.

        This is a security allowlist for process recognition, not a second
        public command parser. The public grammar remains owned by
        ``metor.cli.parser``.

        Args:
            arguments (list[str]): Candidate arguments after the trusted launcher prefix.
            profile_name (str): Expected selected profile.
            require_explicit_profile (bool): Whether the profile option is mandatory.

        Returns:
            bool: Whether the arguments identify one supported daemon start.
        """
        remaining: list[str] = []
        selected_profile: Optional[str] = None
        index: int = 0
        while index < len(arguments):
            token = arguments[index]
            if token.startswith('--profile='):
                if selected_profile is not None:
                    return False
                selected_profile = token.split('=', 1)[1]
            elif token in ('-p', '--profile'):
                if selected_profile is not None or index + 1 >= len(arguments):
                    return False
                index += 1
                selected_profile = arguments[index]
            else:
                remaining.append(token)
            index += 1

        if not remaining or remaining.pop(0) != 'daemon':
            return False
        allowed_flags: set[str] = {
            '--locked',
            '--non-interactive',
            '--startup-session-auth-stdin',
        }
        if len(remaining) != len(set(remaining)) or any(
            token not in allowed_flags for token in remaining
        ):
            return False
        if (
            '--startup-session-auth-stdin' in remaining
            and '--non-interactive' not in remaining
        ):
            return False
        if selected_profile is not None and selected_profile != profile_name:
            return False
        return selected_profile is not None or not require_explicit_profile

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
        validator: Callable[[psutil.Process, _ProcessIdentity], bool],
    ) -> int:
        """
        Terminates one managed process referenced by a PID file.

        Args:
            pid_file (Path): The PID file to inspect.
            profile_name (str): Expected owning profile identity.
            validator (Callable[[psutil.Process, _ProcessIdentity], bool]): Validates process role and persisted launch identity.

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
            if (
                abs(proc.create_time() - identity.create_time)
                >= Constants.PROCESS_CREATE_TIME_TOLERANCE_SEC
            ):
                logger.warning('Skipping cleanup for a reused PID: %s', identity.pid)
                return 0
            if ProcessManager._same_os_owner(proc) is not True:
                logger.warning(
                    'Skipping cleanup with unknown or foreign owner: %s', identity.pid
                )
                return 0
            if not validator(proc, identity):
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
    def cleanup_processes(force: bool = False) -> int:
        """
        Kills managed Metor daemon and Tor processes by reading explicit PID files.
        Prevents killing unrelated system processes by validating each target first.

        Args:
            force (bool): Reserved cleanup mode flag; process termination still requires trusted identity metadata.

        Returns:
            int: The number of processes successfully killed.
        """
        killed: int = 0
        if Constants.DATA.exists():
            for profile_dir in Constants.DATA.iterdir():
                if not ProcessManager._is_owned_profile_directory(
                    profile_dir
                ) or profile_dir.name in (
                    Constants.HIDDEN_SERVICE_DIR,
                    Constants.TOR_DATA_DIR,
                ):
                    continue

                def daemon_validator(
                    proc: psutil.Process,
                    identity: _ProcessIdentity,
                    profile_name: str = profile_dir.name,
                ) -> bool:
                    """Validates one daemon against the current profile iteration.

                    Args:
                        proc (psutil.Process): Candidate daemon process.
                        identity (_ProcessIdentity): Trusted persisted identity.
                        profile_name (str): Captured owning profile name.

                    Returns:
                        bool: Whether the candidate is the recorded daemon.
                    """
                    return ProcessManager._is_metor_daemon_process(
                        proc,
                        profile_name,
                        identity=identity,
                    )

                def tor_validator(
                    proc: psutil.Process,
                    identity: _ProcessIdentity,
                    owned_dir: Path = profile_dir,
                ) -> bool:
                    """Validates one Tor process against the current profile iteration.

                    Args:
                        proc (psutil.Process): Candidate Tor process.
                        identity (_ProcessIdentity): Trusted persisted identity.
                        owned_dir (Path): Captured owning profile directory.

                    Returns:
                        bool: Whether the candidate is the recorded Tor process.
                    """
                    return ProcessManager._is_tor_process(
                        proc,
                        owned_dir,
                        identity=identity,
                    )

                daemon_pid_file: Path = profile_dir / Constants.DAEMON_PID_FILE
                killed += ProcessManager._cleanup_pid_file_process(
                    daemon_pid_file,
                    profile_dir.name,
                    daemon_validator,
                )

                pid_file: Path = profile_dir / Constants.TOR_DATA_DIR / 'tor.pid'
                killed += ProcessManager._cleanup_pid_file_process(
                    pid_file,
                    profile_dir.name,
                    tor_validator,
                )

        return killed
