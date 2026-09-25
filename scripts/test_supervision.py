"""Bounded process supervision and report-bound completion for test workers."""

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time
from typing import BinaryIO

import psutil


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'build' / 'test-report.txt'
MAX_RUNNER_OUTPUT = 1024 * 1024
MAX_RUNNER_STDERR = 64 * 1024
MAX_RUNNER_REPORT = 4 * 1024 * 1024
MAX_COMPLETION_RECORD = 512
MAX_PROGRESS_RECORD = 512
SAFE_TEST_ID = re.compile(r'[A-Za-z_][A-Za-z0-9_.]{0,255}')
RUNNER_WORKER_TIMEOUT_SEC = 3600.0
RUNNER_POLL_SEC = 0.05
RUNNER_DRAIN_SEC = 1.0
RUNNER_STOP_SEC = 3.0
RUNNER_READ_CHUNK = 65536
COMPLETION_VERSION = 1


class _StreamCapture:
    """Drain one worker pipe while retaining only a fixed byte budget."""

    def __init__(self, limit: int) -> None:
        """Create a bounded capture for one binary stream.

        Args:
            limit: Maximum number of bytes retained in memory.
        Returns:
            None
        """
        self.limit = limit
        self.buffer = bytearray()
        self.bytes_seen = 0
        self.overflow = threading.Event()
        self.closed = threading.Event()
        self.read_failed = threading.Event()

    def drain(self, stream: BinaryIO) -> None:
        """Read pipe bytes until EOF without retaining content beyond the limit.

        Args:
            stream: Binary worker pipe owned by this capture.
        Returns:
            None
        """
        try:
            with stream:
                while chunk := os.read(stream.fileno(), RUNNER_READ_CHUNK):
                    self.bytes_seen += len(chunk)
                    remaining = max(0, self.limit - len(self.buffer))
                    self.buffer.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        self.overflow.set()
        except OSError:
            self.read_failed.set()
        finally:
            self.closed.set()


def _owned_descendants(pid: int, started: float) -> list[psutil.Process]:
    """Find only children whose parent chain leads to this new worker PID.

    Args:
        pid: Worker process ID assigned to this invocation.
        started: Worker launch time on the wall clock.
    Returns:
        Known descendants created during this invocation.
    """
    parents = {pid}
    descendants: dict[int, psutil.Process] = {}
    try:
        processes = list(psutil.process_iter(['pid', 'ppid', 'create_time']))
    except psutil.Error:
        return []
    while True:
        added = False
        for candidate in processes:
            try:
                details = candidate.info
                if (
                    details['pid'] not in descendants
                    and details['ppid'] in parents
                    and isinstance(details['create_time'], (int, float))
                    and details['create_time'] >= started - RUNNER_STOP_SEC
                ):
                    descendants[candidate.pid] = candidate
                    parents.add(candidate.pid)
                    added = True
            except (psutil.Error, KeyError):
                continue
        if not added:
            return list(descendants.values())


def _stop_worker(process: subprocess.Popen[bytes], started: float) -> None:
    """Stop the owned worker and its inherited process group within a bound.

    Args:
        process: Worker started by this supervisor.
        started: Worker launch time on the wall clock.
    Returns:
        None
    """
    descendants = _owned_descendants(process.pid, started)
    if os.name == 'nt':
        try:
            subprocess.run(
                ['taskkill', '/T', '/F', '/PID', str(process.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=RUNNER_STOP_SEC,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        if process.poll() is None:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=RUNNER_STOP_SEC)
    except subprocess.TimeoutExpired:
        if os.name != 'nt':
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.kill()
        try:
            process.wait(timeout=RUNNER_STOP_SEC)
        except subprocess.TimeoutExpired:
            pass
    for child in reversed(descendants):
        try:
            child.terminate()
        except psutil.Error:
            pass
    _, live = psutil.wait_procs(descendants, timeout=RUNNER_STOP_SEC)
    for child in live:
        try:
            child.kill()
        except psutil.Error:
            pass


def _report_digest(report: Path) -> str:
    """Hash only a bounded completed report for worker evidence.

    Args:
        report: Report path passed to the current worker.
    Returns:
        SHA-256 digest of its bounded bytes.
    Raises:
        ValueError: The report exceeds its evidence budget.
    """
    with report.open('rb') as source:
        content = source.read(MAX_RUNNER_REPORT + 1)
    if len(content) > MAX_RUNNER_REPORT:
        raise ValueError('Test report exceeds its evidence budget')
    return hashlib.sha256(content).hexdigest()


def write_completion(marker: Path, status: int, report: Path, nonce: str) -> None:
    """Atomically finish one worker's report-bound completion record.

    Args:
        marker: Fresh supervisor-owned completion path.
        status: Status returned by the test runner.
        report: Completed bounded test report.
        nonce: Per-run supervisor nonce.
    Returns:
        None
    """
    record = {
        'version': COMPLETION_VERSION,
        'nonce': nonce,
        'status': status,
        'report_sha256': _report_digest(report),
    }
    temporary = marker.with_suffix('.partial')
    temporary.write_text(json.dumps(record, sort_keys=True), encoding='ascii')
    temporary.replace(marker)


def _completed_status(marker: Path, report: Path, nonce: str, exit_status: int) -> bool:
    """Verify this worker's bounded record, report and process status agree.

    Args:
        marker: Fresh completion path assigned to this worker.
        report: Current run's report path.
        nonce: Per-run supervisor nonce.
        exit_status: Actual worker process status.
    Returns:
        True only for a complete matching result.
    """
    try:
        with marker.open('rb') as source:
            content = source.read(MAX_COMPLETION_RECORD + 1)
        if len(content) > MAX_COMPLETION_RECORD:
            return False
        record = json.loads(content.decode('ascii'))
        if not isinstance(record, dict) or set(record) != {
            'version',
            'nonce',
            'status',
            'report_sha256',
        }:
            return False
        return (
            type(record['version']) is int
            and record['version'] == COMPLETION_VERSION
            and type(record['nonce']) is str
            and record['nonce'] == nonce
            and type(record['status']) is int
            and record['status'] == exit_status
            and type(record['report_sha256']) is str
            and record['report_sha256'] == _report_digest(report)
        )
    except (OSError, UnicodeError, ValueError, TypeError):
        return False


def _emit_safe_worker_hints(output: bytearray) -> None:
    """Show fixed runner errors when completion did not authenticate stdout.

    Args:
        output: Bounded but otherwise untrusted worker stdout bytes.
    Returns:
        None
    """
    allowed = {
        'Test report could not be written.',
        'Test report could not be completed.',
        'Test worker could not finalize its bounded result.',
    }
    for line in output.decode('utf-8', errors='replace').splitlines():
        if line in allowed:
            print(line)


def write_progress(test_id: str) -> None:
    """Write one verified static test ID for a possible supervised abort.

    Args:
        test_id: Full unittest ID from the current case.
    Returns:
        None
    """
    path = os.environ.get('METOR_TEST_PROGRESS')
    if (
        not path
        or os.environ.get('METOR_TEST_PROGRESS_OWNER') != str(os.getpid())
        or SAFE_TEST_ID.fullmatch(test_id) is None
    ):
        return
    temporary = Path(path).with_suffix('.partial')
    try:
        temporary.write_text(test_id + '\n', encoding='ascii')
        temporary.replace(path)
    except OSError:
        return


def _last_progress(path: Path) -> str | None:
    """Read a bounded, static test ID from this worker's fresh progress file.

    Args:
        path: Progress file allocated for this invocation.
    Returns:
        Verified test ID when present, otherwise None.
    """
    try:
        with path.open('rb') as source:
            content = source.read(MAX_PROGRESS_RECORD + 1)
        if len(content) > MAX_PROGRESS_RECORD:
            return None
        test_id = content.decode('ascii').removesuffix('\n')
        return test_id if SAFE_TEST_ID.fullmatch(test_id) else None
    except (OSError, UnicodeError):
        return None


def supervised(
    command: list[str],
    *,
    timeout: float = RUNNER_WORKER_TIMEOUT_SEC,
    max_stdout: int = MAX_RUNNER_OUTPUT,
    max_stderr: int = MAX_RUNNER_STDERR,
    report_path: Path | None = None,
) -> int:
    """Supervise one worker with bounded pipes, lifetime and report evidence.

    Args:
        command: Exact worker process command.
        timeout: Maximum whole-worker time, including test fixture cleanup.
        max_stdout: Maximum safe console bytes retained during execution.
        max_stderr: Maximum private stderr bytes retained during execution.
        report_path: Current worker's report; defaults to the canonical path.
    Returns:
        Verified child status, or failure when evidence is incomplete.
    """
    if timeout <= 0 or max_stdout < 1 or max_stderr < 1:
        raise ValueError('Supervisor limits must be positive')
    report = report_path or REPORT
    with TemporaryDirectory(prefix='metor-tests-') as directory:
        marker = Path(directory) / 'complete.json'
        progress = Path(directory) / 'progress.txt'
        nonce = secrets.token_hex(16)
        environment = os.environ.copy()
        environment['METOR_TEST_COMPLETION'] = str(marker)
        environment['METOR_TEST_REPORT'] = str(report)
        environment['METOR_TEST_NONCE'] = nonce
        environment['METOR_TEST_PROGRESS'] = str(progress)
        try:
            started_wall = time.time()
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=os.name != 'nt',
                creationflags=(
                    getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
                    if os.name == 'nt'
                    else 0
                ),
            )
        except OSError:
            print('Test worker could not start.')
            return 1
        assert process.stdout is not None and process.stderr is not None
        stdout = _StreamCapture(max_stdout)
        stderr = _StreamCapture(max_stderr)
        readers = [
            threading.Thread(target=stdout.drain, args=(process.stdout,), daemon=True),
            threading.Thread(target=stderr.drain, args=(process.stderr,), daemon=True),
        ]
        reason: str | None = None
        deadline = time.monotonic() + timeout
        try:
            for reader in readers:
                reader.start()
            while process.poll() is None:
                if stdout.overflow.is_set() or stderr.overflow.is_set():
                    reason = 'output-limit'
                    break
                if stdout.read_failed.is_set() or stderr.read_failed.is_set():
                    reason = 'stream-read-error'
                    break
                if time.monotonic() >= deadline:
                    reason = 'timeout'
                    break
                time.sleep(RUNNER_POLL_SEC)
            if reason is None:
                for reader in readers:
                    reader.join(RUNNER_DRAIN_SEC)
                if not stdout.closed.is_set() or not stderr.closed.is_set():
                    reason = 'stream-open'
                elif stdout.overflow.is_set() or stderr.overflow.is_set():
                    reason = 'output-limit'
                elif stdout.read_failed.is_set() or stderr.read_failed.is_set():
                    reason = 'stream-read-error'
        except KeyboardInterrupt:
            reason = 'interrupted'
        finally:
            if reason is not None:
                _stop_worker(process, started_wall)
            for reader in readers:
                if reader.ident is not None:
                    reader.join(RUNNER_DRAIN_SEC)
        if reason is not None:
            _emit_safe_worker_hints(stdout.buffer)
            if last_id := _last_progress(progress):
                print(f'Last running test: {last_id}.')
            print(f'Test worker failed supervision: {reason}.')
            return 130 if reason == 'interrupted' else 1
        if stderr.bytes_seen:
            _emit_safe_worker_hints(stdout.buffer)
            if last_id := _last_progress(progress):
                print(f'Last running test: {last_id}.')
            print('Test worker emitted private stderr; content suppressed.')
            return 1
        status = process.returncode
        if status is None or not _completed_status(marker, report, nonce, status):
            _emit_safe_worker_hints(stdout.buffer)
            if last_id := _last_progress(progress):
                print(f'Last running test: {last_id}.')
            label = 'crashed' if status not in (None, 0) else 'incomplete'
            print(f'Test worker ended without a bounded, completed result ({label}).')
            return 1
        sys.stdout.write(stdout.buffer.decode('utf-8', errors='replace'))
        return status
