"""Own one bounded test worker and its spawned process lifetime."""

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import psutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
RUNNER_POLL_SEC = 0.05
RUNNER_STOP_SEC = 3.0
_LINUX_GET_CHILD_SUBREAPER = 37
_LINUX_SET_CHILD_SUBREAPER = 36
_WINDOWS_JOB_KILL_ON_CLOSE = 0x2000
_WINDOWS_JOB_EXTENDED_LIMIT = 9
_WINDOWS_JOB_BASIC_ACCOUNTING = 1
_WINDOWS_CREATE_SUSPENDED = 0x4
_WINDOWS_THREAD_SUSPEND_RESUME = 0x0002


def _windows_last_error() -> int:
    """Read a Win32 error code without importing Windows APIs on POSIX.

    Args:
        None
    Returns:
        Last native error code on Windows.
    """
    return int(getattr(ctypes, 'get_last_error')())


class _WindowsJobBasicLimit(ctypes.Structure):
    """Match the Windows basic job limit information layout."""

    _fields_ = [
        ('PerProcessUserTimeLimit', ctypes.c_longlong),
        ('PerJobUserTimeLimit', ctypes.c_longlong),
        ('LimitFlags', wintypes.DWORD),
        ('MinimumWorkingSetSize', ctypes.c_size_t),
        ('MaximumWorkingSetSize', ctypes.c_size_t),
        ('ActiveProcessLimit', wintypes.DWORD),
        ('Affinity', ctypes.c_size_t),
        ('PriorityClass', wintypes.DWORD),
        ('SchedulingClass', wintypes.DWORD),
    ]


class _WindowsIoCounters(ctypes.Structure):
    """Match the Windows job I/O counter layout."""

    _fields_ = [
        ('ReadOperationCount', ctypes.c_ulonglong),
        ('WriteOperationCount', ctypes.c_ulonglong),
        ('OtherOperationCount', ctypes.c_ulonglong),
        ('ReadTransferCount', ctypes.c_ulonglong),
        ('WriteTransferCount', ctypes.c_ulonglong),
        ('OtherTransferCount', ctypes.c_ulonglong),
    ]


class _WindowsJobExtendedLimit(ctypes.Structure):
    """Match the Windows extended job limit information layout."""

    _fields_ = [
        ('BasicLimitInformation', _WindowsJobBasicLimit),
        ('IoInfo', _WindowsIoCounters),
        ('ProcessMemoryLimit', ctypes.c_size_t),
        ('JobMemoryLimit', ctypes.c_size_t),
        ('PeakProcessMemoryUsed', ctypes.c_size_t),
        ('PeakJobMemoryUsed', ctypes.c_size_t),
    ]


class _WindowsJobAccounting(ctypes.Structure):
    """Match the Windows job accounting query layout."""

    _fields_ = [
        ('TotalUserTime', ctypes.c_longlong),
        ('TotalKernelTime', ctypes.c_longlong),
        ('ThisPeriodTotalUserTime', ctypes.c_longlong),
        ('ThisPeriodTotalKernelTime', ctypes.c_longlong),
        ('TotalPageFaultCount', wintypes.DWORD),
        ('TotalProcesses', wintypes.DWORD),
        ('ActiveProcesses', wintypes.DWORD),
        ('TotalTerminatedProcesses', wintypes.DWORD),
    ]


class _PosixLifetime:
    """Own one new process group and Linux's adopted descendants."""

    def __init__(self) -> None:
        """Record preexisting children before enabling orphan adoption.

        Args:
            None
        Returns:
            None
        """
        if sys.platform == 'win32':
            raise OSError('POSIX worker lifetime is unavailable on Windows')
        self.parent = psutil.Process(os.getpid())
        children = self.parent.children()
        # A Linux subreaper cannot reconstruct the original parent of an
        # orphan. Refuse to launch when another child could create one.
        if sys.platform == 'linux' and children:
            raise OSError('Supervisor already has child processes')
        self.preexisting = {(child.pid, child.create_time()) for child in children}
        self.known: dict[int, tuple[psutil.Process, float]] = {}
        self.process: subprocess.Popen[bytes] | None = None
        self.group_exhausted = False
        self.prctl: object | None = None
        self.old_subreaper: int | None = None
        if sys.platform == 'linux':
            operation = ctypes.CDLL(None, use_errno=True).prctl
            operation.argtypes = [
                ctypes.c_int,
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.c_ulong,
                ctypes.c_ulong,
            ]
            operation.restype = ctypes.c_int
            previous = ctypes.c_int()
            if (
                operation(
                    _LINUX_GET_CHILD_SUBREAPER,
                    ctypes.byref(previous),
                    0,
                    0,
                    0,
                )
                != 0
                or operation(_LINUX_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0
            ):
                raise OSError(ctypes.get_errno(), 'Cannot establish worker ownership')
            self.prctl = operation
            self.old_subreaper = previous.value

    def launch(
        self, command: list[str], environment: dict[str, str]
    ) -> subprocess.Popen[bytes]:
        """Launch the sole worker in a fresh POSIX session.

        Args:
            command: Exact worker command.
            environment: Worker environment with fresh evidence paths.
        Returns:
            Started worker process.
        """
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        self.process = process
        try:
            self._remember(psutil.Process(process.pid))
        except psutil.NoSuchProcess:
            pass
        return process

    def _remember(self, candidate: psutil.Process) -> None:
        """Retain a process handle with its creation identity.

        Args:
            candidate: Observed member of the worker lifetime.
        Returns:
            None
        """
        try:
            created = candidate.create_time()
        except psutil.NoSuchProcess:
            return
        previous = self.known.get(candidate.pid)
        if previous is not None and previous[1] != created:
            raise OSError('Worker process identity changed')
        self.known[candidate.pid] = (candidate, created)

    def _refresh(self) -> None:
        """Observe the group and adopted children before classifying liveness.

        Args:
            None
        Returns:
            None
        """
        if sys.platform == 'win32':
            raise OSError('POSIX worker lifetime is unavailable on Windows')
        process = self.process
        if process is None:
            return
        group_found = False
        if self.old_subreaper is None and not self.group_exhausted:
            for candidate in psutil.process_iter():
                try:
                    if os.getpgid(candidate.pid) == process.pid:
                        group_found = True
                        self._remember(candidate)
                except (ProcessLookupError, PermissionError, psutil.NoSuchProcess):
                    continue
            if not group_found and process.poll() is not None:
                self.group_exhausted = True
        # The caller runs one supervised worker at a time. Linux reparents an
        # escaped-session orphan to this subreaper even after its root exits.
        if self.old_subreaper is not None:
            for candidate in self.parent.children():
                try:
                    identity = (candidate.pid, candidate.create_time())
                except psutil.NoSuchProcess:
                    continue
                if identity not in self.preexisting:
                    self._remember(candidate)
        for owner, created in list(self.known.values()):
            try:
                if owner.create_time() != created:
                    raise OSError('Worker process identity changed')
                for candidate in owner.children(recursive=True):
                    self._remember(candidate)
            except psutil.NoSuchProcess:
                continue

    def live(self) -> list[psutil.Process]:
        """Return only still-running processes with their original identity.

        Args:
            None
        Returns:
            Live owned processes; zombies are already exited.
        """
        self._refresh()
        living: list[psutil.Process] = []
        for candidate, created in self.known.values():
            try:
                if candidate.create_time() != created:
                    raise OSError('Worker process identity changed')
                if candidate.status() not in (psutil.STATUS_DEAD, psutil.STATUS_ZOMBIE):
                    living.append(candidate)
            except psutil.NoSuchProcess:
                continue
        return living

    def _signal(self, processes: list[psutil.Process], hard: bool) -> None:
        """Signal the owned group and detached members with verified identities.

        Args:
            processes: Live members returned by the current scope query.
            hard: Whether to use the final kill signal.
        Returns:
            None
        """
        if sys.platform == 'win32':
            raise OSError('POSIX worker lifetime is unavailable on Windows')
        process = self.process
        if process is None:
            return
        group = False
        for member in processes:
            try:
                if os.getpgid(member.pid) == process.pid:
                    group = True
                elif hard:
                    member.kill()
                else:
                    member.terminate()
            except (ProcessLookupError, psutil.NoSuchProcess):
                continue
        if group:
            try:
                os.killpg(process.pid, signal.SIGKILL if hard else signal.SIGTERM)
            except ProcessLookupError:
                pass

    def stop(self) -> bool:
        """Escalate based on live owned members, not the root's wait status.

        Args:
            None
        Returns:
            True only after all owned processes have exited.
        """
        process = self.process
        if process is None:
            return True
        confirmed = False
        try:
            self._signal(self.live(), hard=False)
            deadline = time.monotonic() + RUNNER_STOP_SEC
            while time.monotonic() < deadline:
                if not self.live():
                    confirmed = True
                    break
                time.sleep(RUNNER_POLL_SEC)
            if not confirmed:
                self._signal(self.live(), hard=True)
                deadline = time.monotonic() + RUNNER_STOP_SEC
                while time.monotonic() < deadline:
                    if not self.live():
                        confirmed = True
                        break
                    time.sleep(RUNNER_POLL_SEC)
        except (OSError, psutil.Error):
            confirmed = False
            try:
                process.kill()
            except OSError:
                pass
            for child, created in self.known.values():
                try:
                    if child.pid != process.pid and child.create_time() == created:
                        child.kill()
                except psutil.Error:
                    continue
        try:
            process.wait(timeout=RUNNER_STOP_SEC)
        except subprocess.TimeoutExpired:
            confirmed = False
        self._reap_adopted()
        return confirmed

    def _reap_adopted(self) -> None:
        """Collect only exited, identity-verified children adopted here.

        Args:
            None
        Returns:
            None
        """
        if sys.platform == 'win32' or self.old_subreaper is None:
            return
        for child, created in self.known.values():
            try:
                if (
                    child.pid != os.getpid()
                    and child.create_time() == created
                    and child.ppid() == os.getpid()
                    and child.status() == psutil.STATUS_ZOMBIE
                ):
                    os.waitpid(child.pid, os.WNOHANG)
            except (ChildProcessError, psutil.NoSuchProcess):
                continue

    def close(self) -> bool:
        """Restore the caller's Linux subreaper setting after this worker.

        Args:
            None
        Returns:
            Whether the previous setting was restored.
        """
        if self.old_subreaper is None:
            return True
        reaped = True
        try:
            self._reap_adopted()
        except (OSError, psutil.Error):
            reaped = False
        operation = self.prctl
        assert callable(operation)
        return (
            operation(_LINUX_SET_CHILD_SUBREAPER, self.old_subreaper, 0, 0, 0) == 0
            and reaped
        )


class _WindowsLifetime:
    """Contain a suspended worker and all descendants in one Windows Job."""

    def __init__(self) -> None:
        """Create a kill-on-close Job Object before starting the worker.

        Args:
            None
        Returns:
            None
        """
        self.kernel = getattr(ctypes, 'WinDLL')('kernel32', use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self.kernel.SetInformationJobObject.restype = wintypes.BOOL
        self.kernel.AssignProcessToJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
        ]
        self.kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        self.kernel.OpenThread.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        self.kernel.OpenThread.restype = wintypes.HANDLE
        self.kernel.ResumeThread.argtypes = [wintypes.HANDLE]
        self.kernel.ResumeThread.restype = wintypes.DWORD
        self.kernel.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        self.kernel.QueryInformationJobObject.restype = wintypes.BOOL
        self.kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.kernel.TerminateJobObject.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.job = self.kernel.CreateJobObjectW(None, None)
        if not self.job:
            raise OSError(_windows_last_error(), 'Cannot create worker Job Object')
        limits = _WindowsJobExtendedLimit()
        limits.BasicLimitInformation.LimitFlags = _WINDOWS_JOB_KILL_ON_CLOSE
        if not self.kernel.SetInformationJobObject(
            self.job,
            _WINDOWS_JOB_EXTENDED_LIMIT,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            self.close()
            raise OSError(_windows_last_error(), 'Cannot configure worker Job Object')
        self.process: subprocess.Popen[bytes] | None = None

    def launch(
        self, command: list[str], environment: dict[str, str]
    ) -> subprocess.Popen[bytes]:
        """Assign a suspended worker to its Job before any child can start.

        Args:
            command: Exact worker command.
            environment: Worker environment with fresh evidence paths.
        Returns:
            Resumed worker process.
        """
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_WINDOWS_CREATE_SUSPENDED
            | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x200),
        )
        self.process = process
        try:
            handle = getattr(process, '_handle')
            if not self.kernel.AssignProcessToJobObject(self.job, handle):
                raise OSError(
                    _windows_last_error(), 'Cannot assign worker to Job Object'
                )
            threads = psutil.Process(process.pid).threads()
            if len(threads) != 1:
                raise OSError('Cannot identify suspended worker thread')
            thread = self.kernel.OpenThread(
                _WINDOWS_THREAD_SUSPEND_RESUME, False, threads[0].id
            )
            if not thread:
                raise OSError(_windows_last_error(), 'Cannot open worker thread')
            try:
                if self.kernel.ResumeThread(thread) == 0xFFFFFFFF:
                    raise OSError(_windows_last_error(), 'Cannot resume worker thread')
            finally:
                self.kernel.CloseHandle(thread)
        except (OSError, psutil.Error):
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=RUNNER_STOP_SEC)
            except subprocess.TimeoutExpired:
                pass
            raise
        return process

    def live(self) -> bool:
        """Query all active processes in the assigned Job Object.

        Args:
            None
        Returns:
            Whether any owned process is still running.
        """
        accounting = _WindowsJobAccounting()
        if not self.kernel.QueryInformationJobObject(
            self.job,
            _WINDOWS_JOB_BASIC_ACCOUNTING,
            ctypes.byref(accounting),
            ctypes.sizeof(accounting),
            None,
        ):
            raise OSError(_windows_last_error(), 'Cannot query worker Job Object')
        return bool(accounting.ActiveProcesses != 0)

    def stop(self) -> bool:
        """Terminate and confirm the entire owned Job within a fixed bound.

        Args:
            None
        Returns:
            True only after all Job processes have exited.
        """
        process = self.process
        if process is None:
            return True
        try:
            if process.poll() is None:
                process.terminate()
            deadline = time.monotonic() + RUNNER_STOP_SEC
            while time.monotonic() < deadline and self.live():
                time.sleep(RUNNER_POLL_SEC)
            if self.live():
                if not self.kernel.TerminateJobObject(self.job, 1):
                    return False
                deadline = time.monotonic() + RUNNER_STOP_SEC
                while time.monotonic() < deadline and self.live():
                    time.sleep(RUNNER_POLL_SEC)
            confirmed = not self.live()
            process.wait(timeout=RUNNER_STOP_SEC)
            return confirmed
        except (OSError, psutil.Error, subprocess.TimeoutExpired):
            try:
                self.kernel.TerminateJobObject(self.job, 1)
            except OSError:
                pass
            try:
                process.wait(timeout=RUNNER_STOP_SEC)
            except (OSError, subprocess.TimeoutExpired):
                pass
            return False

    def close(self) -> bool:
        """Close the Job handle, retaining kill-on-close as a final fence.

        Args:
            None
        Returns:
            Whether the handle was closed.
        """
        return bool(self.kernel.CloseHandle(self.job))
