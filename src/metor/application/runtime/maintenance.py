"""Application-layer helpers for host-local runtime cleanup flows."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from metor.data.profile import ProfileManager
from metor.utils import ProcessManager


@dataclass(frozen=True)
class CleanupRuntimeResult:
    """Structured outcome for one host-local cleanup pass."""

    killed_processes: int
    cleared_runtime_state: int


@dataclass(frozen=True)
class _RuntimeStateSnapshot:
    """Captured local daemon runtime-state ownership for one profile."""

    profile_name: str
    daemon_pid: Optional[int]
    daemon_port: Optional[int]
    had_pid_file: bool
    had_port_file: bool

    @property
    def had_runtime_state(self) -> bool:
        """Indicates whether the snapshot contained any daemon runtime-state files."""

        return self.had_pid_file or self.had_port_file


def _read_runtime_state_file(file_path: Path) -> Optional[int]:
    """
    Reads one runtime-state integer file without mutating profile state.

    Args:
        file_path (Path): The runtime-state file to inspect.

    Returns:
        Optional[int]: The parsed integer value, or None when unavailable.
    """
    if not file_path.exists():
        return None

    try:
        with file_path.open('r') as handle:
            raw_value: str = handle.read().strip()
        return int(raw_value)
    except (OSError, ValueError):
        return None


def _capture_runtime_state(profile_manager: ProfileManager) -> _RuntimeStateSnapshot:
    """
    Captures one local profile's daemon runtime-state ownership before cleanup.

    Args:
        profile_manager (ProfileManager): The local profile manager.

    Returns:
        _RuntimeStateSnapshot: The captured runtime-state snapshot.
    """
    daemon_pid_file: Path = profile_manager.paths.get_daemon_pid_file()
    daemon_port_file: Path = profile_manager.paths.get_daemon_port_file()
    return _RuntimeStateSnapshot(
        profile_name=profile_manager.profile_name,
        daemon_pid=_read_runtime_state_file(daemon_pid_file),
        daemon_port=_read_runtime_state_file(daemon_port_file),
        had_pid_file=daemon_pid_file.exists(),
        had_port_file=daemon_port_file.exists(),
    )


def _clear_stale_runtime_state(
    snapshot: _RuntimeStateSnapshot,
    *,
    force: bool,
) -> bool:
    """
    Clears one profile's daemon runtime-state when the owning instance is stale.

    Args:
        snapshot (_RuntimeStateSnapshot): The pre-cleanup runtime-state snapshot.
        force (bool): Enables rescue cleanup for orphaned or malformed state files.

    Returns:
        bool: True if the profile runtime-state files were cleared.
    """
    if not snapshot.had_runtime_state:
        return False

    profile_manager: ProfileManager = ProfileManager(snapshot.profile_name)
    daemon_pid_file: Path = profile_manager.paths.get_daemon_pid_file()
    daemon_port_file: Path = profile_manager.paths.get_daemon_port_file()

    if snapshot.daemon_pid is not None:
        if ProcessManager.is_pid_running(snapshot.daemon_pid):
            return False

        profile_manager.clear_daemon_port(
            expected_pid=snapshot.daemon_pid,
            expected_port=snapshot.daemon_port,
        )
    elif not force:
        return False
    elif snapshot.daemon_port is not None:
        profile_manager.clear_daemon_port(expected_port=snapshot.daemon_port)
    else:
        profile_manager.clear_daemon_port()

    return not daemon_pid_file.exists() and not daemon_port_file.exists()


def cleanup_local_runtime(force: bool = False) -> CleanupRuntimeResult:
    """
    Terminates managed local processes and clears stale daemon runtime-state files.
    Default cleanup only clears state owned by dead PID-tracked daemon instances.
    Force mode additionally removes orphaned or malformed runtime-state files.

    Args:
        force (bool): Enables the broader rescue cleanup mode.

    Returns:
        CleanupRuntimeResult: The structured cleanup outcome.
    """
    snapshots: list[_RuntimeStateSnapshot] = []
    for profile_name in ProfileManager.get_all_profiles():
        profile_manager: ProfileManager = ProfileManager(profile_name)
        if profile_manager.is_remote():
            continue
        snapshots.append(_capture_runtime_state(profile_manager))

    killed: int = ProcessManager.cleanup_processes(force=force)
    cleared_runtime_state: int = 0

    for snapshot in snapshots:
        if _clear_stale_runtime_state(snapshot, force=force):
            cleared_runtime_state += 1

    return CleanupRuntimeResult(
        killed_processes=killed,
        cleared_runtime_state=cleared_runtime_state,
    )
