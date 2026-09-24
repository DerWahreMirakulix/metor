"""Run the unittest inventory with explicit suites and bounded timing reports."""

import argparse
from collections import Counter
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import importlib
import io
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from types import TracebackType
import unittest
from collections.abc import Iterator


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / 'tests'
# Every test_*.py must be named exactly once. Fast modules must not import
# integration modules as helpers; only explicitly selected modules are loaded.
FAST_MODULES: tuple[str, ...] = (
    'test_cli_literal_boundary',
    'test_ipc_type_validation',
    'test_quality_gate_contract',
    'test_run_tests',
    'test_source_documentation',
    'test_terminal_voice',
    'test_ui_boundaries',
)
INTEGRATION_MODULES: tuple[str, ...] = (
    'test_acceptance_repair_contract',
    'test_api_generation_contract',
    'test_application_runtime_contract',
    'test_chat_contract',
    'test_chat_owned_lifetime',
    'test_cold_unlock_budget',
    'test_client_demux_contract',
    'test_closure_architecture',
    'test_closure_frontend',
    'test_closure_integration',
    'test_closure_security',
    'test_closure_voice_edges',
    'test_contact_qr',
    'test_daemon_bootstrap_contract',
    'test_daemon_hardening',
    'test_daemon_lock_lifecycle',
    'test_data_persistence_contract',
    'test_device_configuration_security',
    'test_documentation_contract',
    'test_final_remediation_contract',
    'test_gui_accessibility',
    'test_gui_audio',
    'test_gui_bootstrap',
    'test_gui_buttons',
    'test_gui_calls',
    'test_gui_capture',
    'test_gui_contacts',
    'test_gui_continuation',
    'test_gui_contract',
    'test_gui_device_lifecycle',
    'test_gui_drop',
    'test_gui_exception_lifecycle',
    'test_gui_fonts',
    'test_gui_handoff',
    'test_gui_history',
    'test_gui_lifecycle',
    'test_gui_live',
    'test_gui_live_control',
    'test_gui_metadata',
    'test_gui_native_route',
    'test_gui_notifications',
    'test_gui_os_lifecycle',
    'test_gui_pages',
    'test_gui_playback',
    'test_gui_press',
    'test_gui_producers',
    'test_gui_profiles',
    'test_gui_purge',
    'test_gui_purge_observation',
    'test_gui_resend',
    'test_gui_root',
    'test_gui_security',
    'test_gui_settings',
    'test_gui_startup_diagnostics',
    'test_gui_text',
    'test_history_contract',
    'test_lock_contract',
    'test_message_architecture_contract',
    'test_notification_delivery',
    'test_platform_contracts',
    'test_profile_path_security',
    'test_profile_storage_security',
    'test_raw_client_contract',
    'test_refactor2_cli_contract',
    'test_release_contract',
    'test_remaining_closure_contract',
    'test_security_contract',
    'test_session_auth_contract',
    'test_settings_contract',
    'test_startup_selection',
    'test_terminal_bootstrap_status',
    'test_terminal_rendering_security',
    'test_terminal_voice_core',
    'test_tor_path_resolution',
    'test_ui_ipc_contract',
    'test_versioning_release',
    'test_voice_contract',
    'test_windows_acl_security',
    'test_windows_installer_branches',
)
REPORT = ROOT / 'build' / 'test-report.txt'
MAX_OUTPUT = 8192
MAX_DETAILS = 10
MAX_RUNNER_OUTPUT = 1024 * 1024
ExcInfo = (
    tuple[type[BaseException], BaseException, TracebackType] | tuple[None, None, None]
)


class CappedOutput(io.TextIOBase):
    """Discard test output while counting a bounded number of characters."""

    def __init__(self) -> None:
        """Create the bounded buffer.

        Args:
            None
        Returns:
            None
        """
        self.size = 0

    def write(self, text: str) -> int:
        """Discard text and count at most the configured output limit.

        Args:
            text: Text written by a test.
        Returns:
            Number of characters accepted by the stream interface.
        """
        self.size = min(MAX_OUTPUT, self.size + len(text))
        return len(text)


@contextmanager
def discard_native_output() -> Iterator[None]:
    """Hide direct file-descriptor writes from tests and their child processes.

    Args:
        None
    Returns:
        None
    """
    sys.stdout.flush()
    sys.stderr.flush()
    original_stdout = os.dup(1)
    original_stderr = os.dup(2)
    try:
        with open(os.devnull, 'w', encoding='utf-8') as sink:
            os.dup2(sink.fileno(), 1)
            os.dup2(sink.fileno(), 2)
            yield
    finally:
        os.dup2(original_stdout, 1)
        os.dup2(original_stderr, 2)
        os.close(original_stdout)
        os.close(original_stderr)


class TimedResult(unittest.TestResult):
    """Record whole-test timings while retaining only bounded failure details."""

    def __init__(self) -> None:
        """Initialize timing and failure accounting.

        Args:
            None
        Returns:
            None
        """
        super().__init__()
        self.started: dict[unittest.case.TestCase, float] = {}
        self.durations: list[tuple[float, str]] = []
        self.failure_details: list[str] = []
        self.failure_count = 0
        self.error_count = 0
        self.skip_count = 0
        self.statuses: dict[str, str] = {}
        self.diagnostics: list[str] = []

    def _exc_info_to_string(self, err: ExcInfo, test: unittest.case.TestCase) -> str:
        """Keep only a known category and source-verified repository locations.

        Args:
            err: Exception triple supplied by unittest.
            test: Case or fixture associated with the exception.
        Returns:
            Bounded diagnostic without exception values or local variables.
        """
        category = (
            'AssertionError'
            if err[0] and issubclass(err[0], AssertionError)
            else (
                err[0].__name__
                if err[0]
                in (
                    OSError,
                    ValueError,
                    TypeError,
                    ImportError,
                    ModuleNotFoundError,
                    RuntimeError,
                    TimeoutError,
                    PermissionError,
                    FileNotFoundError,
                )
                else 'Exception'
            )
        )
        locations: list[str] = []
        traceback = err[2]
        while traceback is not None:
            path = Path(traceback.tb_frame.f_code.co_filename)
            try:
                relative = path.resolve().relative_to(ROOT.resolve())
            except ValueError:
                traceback = traceback.tb_next
                continue
            if path.is_file() and relative.parts[0] in ('src', 'tests', 'scripts'):
                location = f'{relative.as_posix()}:{traceback.tb_lineno}'
                if location not in locations:
                    locations.append(location)
            traceback = traceback.tb_next
        return f'{category} at {", ".join(locations[-3:]) if locations else "repository location unavailable"}'

    def startTest(self, test: unittest.case.TestCase) -> None:
        """Start timing before the case's setUp method.

        Args:
            test: Case about to run.
        Returns:
            None
        """
        self.started[test] = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test: unittest.case.TestCase) -> None:
        """Stop timing after tearDown and registered cleanups.

        Args:
            test: Case that finished.
        Returns:
            None
        """
        self.durations.append((time.perf_counter() - self.started.pop(test), test.id()))
        super().stopTest(test)

    def _record(self, kind: str, test: unittest.case.TestCase) -> None:
        """Record a test ID without serializing exception or subtest values.

        Args:
            kind: Failure or error label.
            test: Parent case, not a subtest with potentially sensitive parameters.
        Returns:
            None
        """
        if len(self.failure_details) < MAX_DETAILS:
            self.failure_details.append(f'{kind}: {test.id()}')

    def addSuccess(self, test: unittest.case.TestCase) -> None:
        """Record successful completion without capturing test output.

        Args:
            test: Completed case.
        Returns:
            None
        """
        super().addSuccess(test)
        self.statuses.setdefault(test.id(), 'ok')

    def addFailure(self, test: unittest.case.TestCase, err: ExcInfo) -> None:
        """Count an assertion failure without retaining its full traceback.

        Args:
            test: Failing case.
            err: unittest exception triple.
        Returns:
            None
        """
        super().addFailure(test, err)
        self.failure_count += 1
        self.statuses[test.id()] = 'fail'
        self._record('FAIL', test)
        self._diagnose(test, err)

    def addError(self, test: unittest.case.TestCase, err: ExcInfo) -> None:
        """Count an unexpected error, including discovery import errors.

        Args:
            test: Erroring case.
            err: unittest exception triple.
        Returns:
            None
        """
        super().addError(test, err)
        self.error_count += 1
        self.statuses[test.id()] = 'error'
        self._record('ERROR', test)
        self._diagnose(test, err)

    def addSkip(self, test: unittest.case.TestCase, reason: str) -> None:
        """Count skipped cases without retaining unbounded reason strings.

        Args:
            test: Skipped case.
            reason: unittest skip reason.
        Returns:
            None
        """
        super().addSkip(test, reason)
        self.skip_count += 1
        self.statuses[test.id()] = 'skip'
        if len(self.diagnostics) < MAX_DETAILS:
            # Only fixed, source-verified skip categories are published.
            category = (
                'platform'
                if 'platform' in reason.lower()
                or 'windows' in reason.lower()
                or 'linux' in reason.lower()
                else 'condition'
            )
            self.diagnostics.append(f'SKIP {test.id()}: {category}')

    def addSubTest(
        self,
        test: unittest.case.TestCase,
        subtest: unittest.case.TestCase,
        err: ExcInfo | None,
    ) -> None:
        """Count failed subtests as failures or errors.

        Args:
            test: Parent case.
            subtest: Failed or successful subtest.
            err: Exception triple or None for success.
        Returns:
            None
        """
        super().addSubTest(test, subtest, err)
        if err is not None:
            if err[0] is not None and issubclass(err[0], test.failureException):
                self.statuses[test.id()] = 'fail'
                self.failure_count += 1
                self._record('FAIL', test)
            else:
                self.statuses[test.id()] = 'error'
                self.error_count += 1
                self._record('ERROR', test)
            self._diagnose(test, err)

    def wasSuccessful(self) -> bool:
        """Treat all recorded errors and assertion failures as unsuccessful.

        Args:
            None
        Returns:
            True only if no failures or errors occurred.
        """
        return super().wasSuccessful()

    def addExpectedFailure(self, test: unittest.case.TestCase, err: ExcInfo) -> None:
        """Retain unittest's expected-failure state without exception values.

        Args:
            test: Expected failing case.
            err: Exception triple.
        Returns:
            None
        """
        super().addExpectedFailure(test, err)
        self.statuses[test.id()] = 'xfail'

    def addUnexpectedSuccess(self, test: unittest.case.TestCase) -> None:
        """Retain unittest's fail-fast and unsuccessful XPASS semantics.

        Args:
            test: Unexpectedly successful case.
        Returns:
            None
        """
        super().addUnexpectedSuccess(test)
        self.statuses[test.id()] = 'xpass'
        self._record('XPASS', test)

    def _diagnose(self, test: unittest.case.TestCase, err: ExcInfo) -> None:
        """Add a bounded phase and safe source category for a failed callback.

        Args:
            test: Parent case or fixture holder.
            err: Exception triple.
        Returns:
            None
        """
        if len(self.diagnostics) >= MAX_DETAILS:
            return
        names: list[str] = []
        traceback = err[2]
        while traceback is not None:
            names.append(traceback.tb_frame.f_code.co_name)
            traceback = traceback.tb_next
        phase = (
            'Import'
            if is_import_error(test)
            else 'Cleanup'
            if 'doCleanups' in names
            or 'doClassCleanups' in names
            or 'doModuleCleanups' in names
            or 'tearDown' in names
            or 'tearDownClass' in names
            or 'tearDownModule' in names
            else 'Setup'
            if 'setUp' in names or 'setUpClass' in names or 'setUpModule' in names
            else 'Test'
        )
        self.diagnostics.append(
            f'{phase} {test.id()}: {self._exc_info_to_string(err, test)}'
        )


def cases(suite: unittest.TestSuite) -> list[unittest.case.TestCase]:
    """Flatten discovered suites without executing any tests.

    Args:
        suite: Nested suite returned by unittest discovery.
    Returns:
        Ordered individual cases, including failed imports.
    """
    found: list[unittest.case.TestCase] = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            found.extend(cases(item))
        else:
            found.append(item)
    return found


def group(test: unittest.case.TestCase) -> str:
    """Return the explicit classification for a discovered case.

    Args:
        test: Discovered case.
    Returns:
        Fast or integration group.
    Raises:
        ValueError: The test's module is not in the manifest.
    """
    module = test.__class__.__module__
    if module in FAST_MODULES:
        return 'fast'
    if module in INTEGRATION_MODULES:
        return 'integration'
    raise ValueError('Discovered test outside the explicit manifest')


def validate_manifest() -> str | None:
    """Check every test filename is classified exactly once before imports.

    Args:
        None
    Returns:
        A safe diagnostic on mismatch, or None if the inventory is exact.
    """
    modules = FAST_MODULES + INTEGRATION_MODULES
    duplicates = sum(count - 1 for count in Counter(modules).values() if count > 1)
    files = {path.stem for path in TESTS.glob('test_*.py')}
    unknown = len(files - set(modules))
    missing = len(set(modules) - files)
    if not files or duplicates or unknown or missing:
        return (
            f'Manifest invalid: {unknown} unclassified files, '
            f'{missing} missing files, {duplicates} duplicate entries'
        )
    return None


def safe_category(error: BaseException | None) -> str:
    """Name only a fixed known built-in exception family.

    Args:
        error: Exception object whose value remains private.
    Returns:
        Safe category label.
    """
    kind = type(error)
    return (
        kind.__name__
        if kind
        in {
            AssertionError,
            OSError,
            ValueError,
            TypeError,
            ImportError,
            ModuleNotFoundError,
            RuntimeError,
            TimeoutError,
            PermissionError,
            FileNotFoundError,
        }
        else 'Exception'
    )


def discover(
    modules: tuple[str, ...],
) -> tuple[list[unittest.case.TestCase], list[tuple[str, str]]]:
    """Import only selected modules and count unexpected import exceptions.

    Args:
        modules: Explicitly classified module names for the requested suite.
    Returns:
        Ordered cases and number of import exceptions caught outside unittest.
    """
    loader = unittest.TestLoader()
    found: list[unittest.case.TestCase] = []
    failed_modules: list[tuple[str, str]] = []
    for module in modules:
        try:
            found.extend(cases(loader.loadTestsFromName(module)))
        except (Exception, SystemExit) as exc:
            # No exception messages or traceback may reach CI or the report.
            failed_modules.append((module, safe_category(exc)))
    return found, failed_modules


def is_import_error(test: unittest.case.TestCase) -> bool:
    """Identify unittest discovery's synthetic import failure case.

    Args:
        test: Discovered case.
    Returns:
        True for a failed test module import.
    """
    return (test.__class__.__module__, test.__class__.__name__) == (
        'unittest.loader',
        '_FailedTest',
    )


def validate_cases(
    found: list[unittest.case.TestCase],
    modules: tuple[str, ...],
    failed_modules: int | list[tuple[str, str]] = 0,
) -> str | None:
    """Reject empty, imported-failure, duplicate-ID, or unexpected test suites.

    Args:
        found: Cases loaded from the selected modules.
        modules: Names allowed in this suite.
        failed_modules: Import exceptions caught outside unittest.
    Returns:
        A safe diagnostic or None if all cases belong to this suite.
    """
    imports = (
        len(failed_modules) if isinstance(failed_modules, list) else failed_modules
    ) + sum(is_import_error(test) for test in found)
    duplicates = sum(
        count - 1
        for count in Counter(test.id() for test in found).values()
        if count > 1
    )
    unexpected = sum(
        test.__class__.__module__ not in modules
        for test in found
        if not is_import_error(test)
    )
    if not found or imports or duplicates or unexpected:
        return (
            f'Discovery invalid: {imports} import errors, '
            f'{duplicates} duplicate test IDs, {unexpected} unexpected IDs, '
            f'{len(found)} loaded cases'
        )
    return None


def emit(lines: list[str]) -> None:
    """Print a safe bounded summary and save it under an ignored build path.

    Args:
        lines: Preformatted lines without exception strings or captured output.
    Returns:
        None
    """
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    for line in lines:
        print(line)
    print('Report: build/test-report.txt')


def main(argv: list[str] | None = None) -> int:
    """Select and run tests, with optional locally installed coverage.

    Args:
        argv: CLI arguments, or None for sys.argv.
    Returns:
        Process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--suite', choices=('fast', 'integration', 'all'), default='all'
    )
    parser.add_argument('--match', help='substring of full unittest test ID')
    parser.add_argument(
        '--module',
        action='append',
        default=[],
        help='explicit manifest module to import (repeatable)',
    )
    parser.add_argument(
        '--failfast', action='store_true', help='stop after first failure'
    )
    parser.add_argument(
        '--durations',
        type=int,
        default=MAX_DETAILS,
        help='number of slow cases to print',
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='print every selected test ID without running tests',
    )
    parser.add_argument('--coverage', action='store_true', help='require coverage.py')
    args = parser.parse_args(argv)
    if not 0 <= args.durations <= MAX_OUTPUT // 100:
        parser.error('durations must be between 0 and 81')
    started = time.perf_counter()
    invalid = validate_manifest()
    if invalid is not None:
        emit([invalid])
        return 1
    # unittest.loadTestsFromName needs both checkout imports and top-level test helpers.
    for path in (ROOT, TESTS):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    modules = (
        FAST_MODULES
        if args.suite == 'fast'
        else INTEGRATION_MODULES
        if args.suite == 'integration'
        else FAST_MODULES + INTEGRATION_MODULES
    )
    if args.module:
        if len(args.module) != len(set(args.module)) or any(
            module not in modules for module in args.module
        ):
            emit(['Invalid or duplicate module selection.'])
            return 1
        modules = tuple(module for module in modules if module in args.module)
    output = CappedOutput()
    with discard_native_output(), redirect_stdout(output), redirect_stderr(output):
        found, failed_modules = discover(modules)
    invalid = validate_cases(found, modules, failed_modules)
    if invalid is not None:
        failed_names = failed_modules.copy() if isinstance(failed_modules, list) else []
        for test in found:
            if is_import_error(test):
                name = getattr(test, '_testMethodName', '')
                error = getattr(test, '_exception', None)
                failed_names.append(
                    (
                        name if name in modules else 'unclassified module',
                        safe_category(error),
                    )
                )
        emit(
            [invalid]
            + [
                f'  Import {name}: {category}'
                for name, category in failed_names[:MAX_DETAILS]
            ]
        )
        return 1
    counts = Counter(group(test) for test in found)
    inventory = (
        f'Inventory ({args.suite}): {len(found)} loaded; '
        f'{counts["fast"]} fast; {counts["integration"]} integration'
    )
    selected = [test for test in found if args.match is None or args.match in test.id()]
    if not selected:
        emit([inventory, 'No tests matched the requested suite/filter.'])
        return 1
    if args.list:
        emit([inventory, f'Listed {len(selected)} test IDs'])
        for test in selected:
            print(test.id())
        return 0
    coverage = None
    if args.coverage:
        try:
            coverage_module = importlib.import_module('coverage')
        except ImportError:
            emit(
                [
                    inventory,
                    'Coverage unavailable: install coverage.py in the selected environment.',
                ]
            )
            return 1
        coverage_path = ROOT / 'build' / '.coverage'
        coverage_path.parent.mkdir(parents=True, exist_ok=True)
        coverage = coverage_module.Coverage(
            source=['metor'], data_file=str(coverage_path)
        )
        coverage.start()
    result = TimedResult()
    result.failfast = args.failfast
    interrupted = False
    try:
        with discard_native_output(), redirect_stdout(output), redirect_stderr(output):
            unittest.TestSuite(selected).run(result)
    except (Exception, KeyboardInterrupt, SystemExit):
        interrupted = True
    finally:
        if coverage is not None:
            coverage.stop()
            coverage.save()
    elapsed = time.perf_counter() - started
    for test in selected:
        result.statuses.setdefault(test.id(), 'unknown')
    # unittest reports fixture skips on synthetic holders rather than each case.
    for holder, _reason in result.skipped:
        holder_id = holder.id()
        if holder_id.startswith('setUpClass (') or holder_id.startswith(
            'setUpModule ('
        ):
            target = holder_id.split('(', 1)[1].rstrip(')')
            for test in selected:
                if (
                    test.id().startswith(target + '.')
                    and result.statuses[test.id()] == 'unknown'
                ):
                    result.statuses[test.id()] = 'skip'
    unknown = sum(result.statuses[test.id()] == 'unknown' for test in selected)
    selected_skips = sum(result.statuses[test.id()] == 'skip' for test in selected)
    lines = [
        inventory,
        f'Ran {result.testsRun}/{len(selected)} {args.suite} tests in {elapsed:.3f}s '
        f'(failures={result.failure_count}, errors={result.error_count}, skips={selected_skips}, '
        f'xfail={len(result.expectedFailures)}, xpass={len(result.unexpectedSuccesses)})',
    ]
    lines.extend(
        f'  slow {seconds:.3f}s {name}'
        for seconds, name in sorted(result.durations, reverse=True)[: args.durations]
    )
    lines.extend(f'  {detail}' for detail in result.failure_details)
    lines.extend(f'  {detail}' for detail in result.diagnostics)
    if interrupted:
        lines.append('  Run interrupted before complete results.')
    if result.failure_count + result.error_count > MAX_DETAILS:
        lines.append(
            f'  ... {result.failure_count + result.error_count - MAX_DETAILS} more failures/errors'
        )
    if output.size:
        lines.append(f'Captured test output: up to {MAX_OUTPUT} characters discarded')
    if coverage is not None:
        percent = coverage.report(file=CappedOutput())
        lines.append(f'Coverage (metor): {percent:.1f}% (build/.coverage)')
    if unknown:
        lines.append(f'  Incomplete: {unknown} selected cases have no result.')
    emit(lines)
    with REPORT.open('a', encoding='utf-8') as report:
        timed_ids: set[str] = set()
        for seconds, name in result.durations:
            timed_ids.add(name)
            report.write(
                f'{name}\t{result.statuses.get(name, "unknown")}\t{seconds:.6f}\n'
            )
        for test in selected:
            if test.id() not in timed_ids:
                report.write(f'{test.id()}\t{result.statuses[test.id()]}\t-\n')
    return 0 if result.wasSuccessful() and not interrupted and not unknown else 1


def supervised(command: list[str]) -> int:
    """Require a child completion marker so abrupt exits cannot look green.

    Args:
        command: Exact worker process command.
    Returns:
        Child status, or failure when its result was incomplete.
    """
    with TemporaryDirectory(prefix='metor-tests-') as directory:
        marker = Path(directory) / 'complete'
        environment = os.environ.copy()
        environment['METOR_TEST_COMPLETION'] = str(marker)
        try:
            completed = subprocess.run(
                command,
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            print('Test worker could not start.')
            return 1
        if not marker.is_file() or len(completed.stdout) > MAX_RUNNER_OUTPUT:
            print('Test worker ended without a bounded, completed result.')
            return 1
        sys.stdout.write(completed.stdout)
        if completed.stderr:
            print(
                'Test worker stderr suppressed; use the bounded report for diagnosis.'
            )
        return completed.returncode


if __name__ == '__main__':
    if '-h' in sys.argv[1:] or '--help' in sys.argv[1:]:
        sys.exit(main())
    completion = os.environ.get('METOR_TEST_COMPLETION')
    if completion:
        status = main()
        Path(completion).write_text('complete', encoding='ascii')
        sys.exit(status)
    sys.exit(supervised([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]))
