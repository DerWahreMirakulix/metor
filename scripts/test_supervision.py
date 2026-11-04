"""Bounded process supervision and report-bound completion for test workers."""

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
from tempfile import TemporaryDirectory
import threading
import time
from typing import BinaryIO

import psutil

from scripts.test_worker_lifetime import _PosixLifetime, _WindowsLifetime


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
_CLOCK = time.monotonic
_SUPERVISOR_LOCK = threading.Lock()


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
        temporary.write_bytes((test_id + '\n').encode('ascii'))
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
        if not content.endswith(b'\n'):
            return None
        test_id = content[:-1].decode('ascii')
        return test_id if SAFE_TEST_ID.fullmatch(test_id) else None
    except (OSError, UnicodeError):
        return None


def _supervised_locked(
    command: list[str],
    *,
    timeout: float = RUNNER_WORKER_TIMEOUT_SEC,
    max_stdout: int = MAX_RUNNER_OUTPUT,
    max_stderr: int = MAX_RUNNER_STDERR,
    report_path: Path | None = None,
) -> int:
    """Run one worker while this process exclusively owns its child scope.

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
        scope: _PosixLifetime | _WindowsLifetime | None = None
        try:
            scope = _WindowsLifetime() if os.name == 'nt' else _PosixLifetime()
            process = scope.launch(command, environment)
        except (OSError, psutil.Error):
            cleanup_confirmed = True
            if scope is not None:
                try:
                    cleanup_confirmed = scope.stop()
                except BaseException:
                    cleanup_confirmed = False
                try:
                    cleanup_confirmed = scope.close() and cleanup_confirmed
                except BaseException:
                    cleanup_confirmed = False
            print('Test worker could not start.')
            if not cleanup_confirmed:
                print('Test worker startup cleanup could not be confirmed.')
            return 1
        assert process.stdout is not None and process.stderr is not None
        stdout = _StreamCapture(max_stdout)
        stderr = _StreamCapture(max_stderr)
        readers = [
            threading.Thread(target=stdout.drain, args=(process.stdout,), daemon=True),
            threading.Thread(target=stderr.drain, args=(process.stderr,), daemon=True),
        ]
        reason: str | None = None
        deadline = _CLOCK() + timeout
        cleanup_confirmed = False
        scope_restored = False
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
                if _CLOCK() >= deadline:
                    reason = 'timeout'
                    break
                time.sleep(RUNNER_POLL_SEC)
            if reason is None and scope.live():
                reason = 'process-left-running'
        except KeyboardInterrupt:
            reason = 'interrupted'
        except (OSError, psutil.Error):
            reason = 'ownership-unconfirmed'
        except RuntimeError:
            reason = 'stream-start-error'
        finally:
            try:
                cleanup_confirmed = scope.stop()
            except BaseException:
                cleanup_confirmed = False
            for reader in readers:
                if reader.ident is not None:
                    try:
                        reader.join(RUNNER_DRAIN_SEC)
                    except BaseException:
                        reason = reason or 'stream-read-error'
            try:
                scope_restored = scope.close()
            except BaseException:
                scope_restored = False
        if not cleanup_confirmed or not scope_restored:
            reason = reason or 'ownership-unconfirmed'
        if not stdout.closed.is_set() or not stderr.closed.is_set():
            reason = reason or 'stream-open'
        if stdout.overflow.is_set() or stderr.overflow.is_set():
            reason = reason or 'output-limit'
        if stdout.read_failed.is_set() or stderr.read_failed.is_set():
            reason = reason or 'stream-read-error'
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


def supervised(
    command: list[str],
    *,
    timeout: float = RUNNER_WORKER_TIMEOUT_SEC,
    max_stdout: int = MAX_RUNNER_OUTPUT,
    max_stderr: int = MAX_RUNNER_STDERR,
    report_path: Path | None = None,
) -> int:
    """Serialize one bounded worker lifetime in this supervisor process.

    Args:
        command: Exact worker process command.
        timeout: Maximum worker execution time.
        max_stdout: Maximum safe console bytes retained.
        max_stderr: Maximum private stderr bytes retained.
        report_path: Current worker's report; defaults to the canonical path.
    Returns:
        Verified child status, or failure when evidence is incomplete.
    """
    with _SUPERVISOR_LOCK:
        return _supervised_locked(
            command,
            timeout=timeout,
            max_stdout=max_stdout,
            max_stderr=max_stderr,
            report_path=report_path,
        )
