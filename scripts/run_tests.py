"""Run the unittest inventory with explicit suites and bounded timing reports."""

import argparse
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
import importlib
import io
from pathlib import Path
import sys
import time
from types import TracebackType
import unittest


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
    'test_ui_boundaries',
)
INTEGRATION_MODULES: tuple[str, ...] = (
    'test_acceptance_repair_contract',
    'test_api_generation_contract',
    'test_application_runtime_contract',
    'test_chat_contract',
    'test_chat_owned_lifetime',
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
    'test_terminal_voice',
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
        self.statuses.setdefault(test.id(), 'ok')

    def addFailure(self, test: unittest.case.TestCase, err: ExcInfo) -> None:
        """Count an assertion failure without retaining its full traceback.

        Args:
            test: Failing case.
            err: unittest exception triple.
        Returns:
            None
        """
        self.failure_count += 1
        self.statuses[test.id()] = 'fail'
        self._record('FAIL', test)

    def addError(self, test: unittest.case.TestCase, err: ExcInfo) -> None:
        """Count an unexpected error, including discovery import errors.

        Args:
            test: Erroring case.
            err: unittest exception triple.
        Returns:
            None
        """
        self.error_count += 1
        self.statuses[test.id()] = 'error'
        self._record('ERROR', test)

    def addSkip(self, test: unittest.case.TestCase, reason: str) -> None:
        """Count skipped cases without retaining unbounded reason strings.

        Args:
            test: Skipped case.
            reason: unittest skip reason.
        Returns:
            None
        """
        self.skip_count += 1
        self.statuses[test.id()] = 'skip'

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
        if err is not None:
            if err[0] is not None and issubclass(err[0], test.failureException):
                self.statuses[test.id()] = 'fail'
                self.failure_count += 1
                self._record('FAIL', test)
            else:
                self.statuses[test.id()] = 'error'
                self.error_count += 1
                self._record('ERROR', test)

    def wasSuccessful(self) -> bool:
        """Treat all recorded errors and assertion failures as unsuccessful.

        Args:
            None
        Returns:
            True only if no failures or errors occurred.
        """
        return not (self.failure_count or self.error_count)


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


def discover(modules: tuple[str, ...]) -> tuple[list[unittest.case.TestCase], int]:
    """Import only selected modules and count unexpected import exceptions.

    Args:
        modules: Explicitly classified module names for the requested suite.
    Returns:
        Ordered cases and number of import exceptions caught outside unittest.
    """
    loader = unittest.TestLoader()
    found: list[unittest.case.TestCase] = []
    failed_modules = 0
    for module in modules:
        try:
            found.extend(cases(loader.loadTestsFromName(module)))
        except (Exception, SystemExit):
            # No exception messages or traceback may reach CI or the report.
            failed_modules += 1
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
    failed_modules: int = 0,
) -> str | None:
    """Reject empty, imported-failure, duplicate-ID, or unexpected test suites.

    Args:
        found: Cases loaded from the selected modules.
        modules: Names allowed in this suite.
        failed_modules: Import exceptions caught outside unittest.
    Returns:
        A safe diagnostic or None if all cases belong to this suite.
    """
    imports = failed_modules + sum(is_import_error(test) for test in found)
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
    output = CappedOutput()
    with redirect_stdout(output), redirect_stderr(output):
        found, failed_modules = discover(modules)
    invalid = validate_cases(found, modules, failed_modules)
    if invalid is not None:
        emit([invalid])
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
    try:
        with redirect_stdout(output), redirect_stderr(output):
            unittest.TestSuite(selected).run(result)
    finally:
        if coverage is not None:
            coverage.stop()
            coverage.save()
    elapsed = time.perf_counter() - started
    lines = [
        inventory,
        f'Ran {result.testsRun}/{len(selected)} {args.suite} tests in {elapsed:.3f}s '
        f'(failures={result.failure_count}, errors={result.error_count}, skips={result.skip_count})',
    ]
    lines.extend(
        f'  slow {seconds:.3f}s {name}'
        for seconds, name in sorted(result.durations, reverse=True)[: args.durations]
    )
    lines.extend(f'  {detail}' for detail in result.failure_details)
    if result.failure_count + result.error_count > MAX_DETAILS:
        lines.append(
            f'  ... {result.failure_count + result.error_count - MAX_DETAILS} more failures/errors'
        )
    if output.size:
        lines.append(f'Captured test output: up to {MAX_OUTPUT} characters discarded')
    if coverage is not None:
        percent = coverage.report(file=CappedOutput())
        lines.append(f'Coverage (metor): {percent:.1f}% (build/.coverage)')
    emit(lines)
    with REPORT.open('a', encoding='utf-8') as report:
        for seconds, name in result.durations:
            report.write(
                f'{name}\t{result.statuses.get(name, "unknown")}\t{seconds:.6f}\n'
            )
    return 0 if result.wasSuccessful() and result.testsRun == len(selected) else 1


if __name__ == '__main__':
    sys.exit(main())
