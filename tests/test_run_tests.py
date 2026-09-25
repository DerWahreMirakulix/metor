"""Contract tests for the bounded, fail-closed unittest runner."""

from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import psutil
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from textwrap import dedent
import threading
import time
import unittest
from typing import cast
from unittest.mock import Mock, patch

from scripts import ci_impact, run_tests, test_supervision
from scripts.test_worker_lifetime import _PosixLifetime, _WindowsLifetime
from metor.client import MetorRequestRejectedError
from metor.core.api import InternalErrorEvent


class FastExample(unittest.TestCase):
    """A fixture-free case for selection tests."""

    def exercise_fast(self) -> None:
        """Pass without side effects.

        Args:
            None
        Returns:
            None
        """


class IntegrationExample(unittest.TestCase):
    """A synthetic case classified as an integration module."""

    def exercise_integration(self) -> None:
        """Pass without side effects.

        Args:
            None
        Returns:
            None
        """


class LifecycleExample(unittest.TestCase):
    """Exercise setup and cleanup inside a measured case."""

    def setUp(self) -> None:
        """Spend time before the test body.

        Args:
            None
        Returns:
            None
        """
        time.sleep(0.01)
        self.addCleanup(time.sleep, 0.01)

    def exercise_lifecycle(self) -> None:
        """Leave cleanup for the runner to measure.

        Args:
            None
        Returns:
            None
        """


class FailureExample(unittest.TestCase):
    """Supply an assertion failure to the runner."""

    def exercise_failure(self) -> None:
        """Raise a bounded failure.

        Args:
            None
        Returns:
            None
        """
        self.fail('token=do-not-log')


class SubtestExample(unittest.TestCase):
    """Provide a failing subtest without ordinary assertions."""

    def exercise_subtest(self) -> None:
        """Report a failed subtest through unittest's result callback.

        Args:
            None
        Returns:
            None
        """
        with self.subTest(value='private-subtest-value'):
            self.fail('token=private-subtest-failure')


class RunnerTests(unittest.TestCase):
    """Check inventory, selection, failure handling and timing."""

    def invoke(self, found: list[unittest.TestCase], *args: str) -> tuple[int, str]:
        """Invoke the CLI against controlled discovery results.

        Args:
            found: Synthetic discovered cases.
            *args: CLI options.
        Returns:
            Exit status and bounded console output.
        """
        stream = io.StringIO()
        with patch.object(run_tests, 'discover', return_value=(found, 0)):
            with redirect_stdout(stream), redirect_stderr(stream):
                status = run_tests.main(list(args))
        return status, stream.getvalue()

    def test_suite_inventory_and_filter(self) -> None:
        """Keep explicit groups separate and report loaded inventory.

        Args:
            None
        Returns:
            None
        """
        with patch.object(IntegrationExample, '__module__', 'test_closure_integration'):
            found = [
                FastExample('exercise_fast'),
                IntegrationExample('exercise_integration'),
            ]
            self.assertEqual(run_tests.group(found[1]), 'integration')
            status, text = self.invoke(found[:1], '--suite', 'fast')
            self.assertEqual(status, 0)
            self.assertIn('Inventory (fast): 1 loaded; 1 fast; 0 integration', text)
            self.assertIn('Ran 1/1 fast', text)
            status, text = self.invoke(found[1:], '--suite', 'integration')
            self.assertEqual(status, 0)
            self.assertIn('Ran 1/1 integration', text)
            status, text = self.invoke(
                found, '--suite', 'all', '--match', 'exercise_fast'
            )
            self.assertEqual(status, 0)
            self.assertIn('Ran 1/1 all', text)

    def test_zero_matches_and_empty_discovery_fail(self) -> None:
        """Never turn an empty selection into a green CI run.

        Args:
            None
        Returns:
            None
        """
        self.assertEqual(
            self.invoke([FastExample('exercise_fast')], '--match', 'missing')[0], 1
        )
        self.assertEqual(self.invoke([], '--list')[0], 1)

    def test_import_error_fails_even_outside_selected_suite(self) -> None:
        """Do not hide failed imports with filters or inventory mode.

        Args:
            None
        Returns:
            None
        """
        failed = cast(
            unittest.TestCase,
            next(iter(unittest.TestLoader().loadTestsFromName('test_broken'))),
        )
        for args in (('--suite', 'fast'), ('--list',), ('--match', 'exercise_fast')):
            status, text = self.invoke([FastExample('exercise_fast'), failed], *args)
            self.assertEqual(status, 1)
            self.assertIn('1 import errors', text)
            self.assertNotIn('Traceback', text)

    def test_list_shows_complete_ids_and_rejects_duplicate_ids(self) -> None:
        """Inventory emits full IDs while duplicate case IDs fail before execution.

        Args:
            None
        Returns:
            None
        """
        example = FastExample('exercise_fast')
        status, text = self.invoke([example], '--suite', 'fast', '--list')
        self.assertEqual(status, 0)
        self.assertIn('test_run_tests.FastExample.exercise_fast', text)
        status, text = self.invoke([example, FastExample('exercise_fast')])
        self.assertEqual(status, 1)
        self.assertIn('1 duplicate test IDs', text)

    def test_manifest_and_unexpected_ids_fail_closed(self) -> None:
        """Reject unknown modules, repeated manifest entries and foreign cases.

        Args:
            None
        Returns:
            None
        """
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'test_new.py').write_text('pass\n', encoding='utf-8')
            with patch.object(run_tests, 'TESTS', root):
                with patch.object(run_tests, 'FAST_MODULES', ('test_new',)):
                    with patch.object(run_tests, 'INTEGRATION_MODULES', ()):
                        self.assertIsNone(run_tests.validate_manifest())
                        (root / 'test_unknown.py').write_text(
                            'pass\n', encoding='utf-8'
                        )
                        self.assertIn(
                            '1 unclassified files', run_tests.validate_manifest() or ''
                        )
                        with patch.object(run_tests, 'REPORT', root / 'report.txt'):
                            with patch.object(run_tests, 'discover') as imported:
                                with redirect_stdout(io.StringIO()):
                                    self.assertEqual(
                                        run_tests.main(['--suite', 'fast']), 1
                                    )
                                imported.assert_not_called()
                        (root / 'test_unknown.py').unlink()
                        with patch.object(
                            run_tests, 'FAST_MODULES', ('test_new', 'test_new')
                        ):
                            self.assertIn(
                                '1 duplicate entries',
                                run_tests.validate_manifest() or '',
                            )
        with patch.object(IntegrationExample, '__module__', 'test_not_classified'):
            status, text = self.invoke([IntegrationExample('exercise_integration')])
        self.assertEqual(status, 1)
        self.assertIn('1 unexpected IDs', text)

    def test_fast_does_not_import_integration_modules(self) -> None:
        """Load only the selected module even when another raises on import.

        Args:
            None
        Returns:
            None
        """
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'test_runner_fast_fixture.py').write_text(
                'import unittest\nclass Example(unittest.TestCase):\n'
                '    def test_ok(self): pass\n',
                encoding='utf-8',
            )
            (root / 'test_runner_integration_fixture.py').write_text(
                "raise RuntimeError('token=do-not-log')\n", encoding='utf-8'
            )
            with (
                patch.object(run_tests, 'TESTS', root),
                patch.object(run_tests, 'FAST_MODULES', ('test_runner_fast_fixture',)),
                patch.object(
                    run_tests,
                    'INTEGRATION_MODULES',
                    ('test_runner_integration_fixture',),
                ),
                patch.object(run_tests, 'REPORT', root / 'report.txt'),
                patch.object(sys, 'path', sys.path.copy()),
                patch.dict(sys.modules),
            ):
                stream = io.StringIO()
                with redirect_stdout(stream), redirect_stderr(stream):
                    status = run_tests.main(['--suite', 'fast', '--list'])
                self.assertEqual(status, 0)
                self.assertIn(
                    'test_runner_fast_fixture.Example.test_ok', stream.getvalue()
                )
                self.assertNotIn('test_runner_integration_fixture', sys.modules)
                with redirect_stdout(stream), redirect_stderr(stream):
                    status = run_tests.main(['--suite', 'integration'])
                self.assertEqual(status, 1)
                self.assertIn('1 import errors', stream.getvalue())
                self.assertIn(
                    'Import test_runner_integration_fixture: RuntimeError',
                    stream.getvalue(),
                )
                self.assertNotIn('token=do-not-log', stream.getvalue())
                self.assertNotIn(
                    'token=do-not-log',
                    (root / 'report.txt').read_text(encoding='utf-8'),
                )

    def test_failure_and_lifecycle_duration(self) -> None:
        """Measure setup plus cleanup and surface assertion failures.

        Args:
            None
        Returns:
            None
        """
        result = run_tests.TimedResult()
        unittest.TestSuite([LifecycleExample('exercise_lifecycle')]).run(result)
        self.assertEqual(result.testsRun, 1)
        self.assertGreaterEqual(result.durations[0][0], 0.02)
        status, text = self.invoke([FailureExample('exercise_failure')])
        self.assertEqual(status, 1)
        self.assertIn('failures=1', text)
        self.assertIn('FAIL: test_run_tests.FailureExample.exercise_failure', text)
        self.assertNotIn('do-not-log', text)
        self.assertNotIn('do-not-log', run_tests.REPORT.read_text(encoding='utf-8'))

    def test_subtest_and_missing_coverage_fail(self) -> None:
        """Reject subtest failures and absent optional coverage dependencies.

        Args:
            None
        Returns:
            None
        """
        status, text = self.invoke([SubtestExample('exercise_subtest')])
        self.assertEqual(status, 1)
        self.assertIn('failures=1', text)
        self.assertNotIn('private-subtest-value', text)
        self.assertNotIn('private-subtest-failure', text)
        with patch.object(
            run_tests.importlib, 'import_module', side_effect=ImportError
        ):
            status, text = self.invoke([FastExample('exercise_fast')], '--coverage')
        self.assertEqual(status, 1)
        self.assertIn('Coverage unavailable', text)

    def test_coverage_reports_only_bounded_total(self) -> None:
        """Start and stop optional coverage without listing every source file.

        Args:
            None
        Returns:
            None
        """
        module = Mock()
        module.Coverage.return_value.report.return_value = 75.0
        with patch.object(run_tests.importlib, 'import_module', return_value=module):
            status, text = self.invoke([FastExample('exercise_fast')], '--coverage')
        self.assertEqual(status, 0)
        self.assertIn('Coverage (metor): 75.0% (build/.coverage)', text)
        module.Coverage.return_value.start.assert_called_once_with()
        module.Coverage.return_value.stop.assert_called_once_with()
        module.Coverage.return_value.save.assert_called_once_with()

    def test_ci_runs_full_matrix_and_keeps_branch_acceptance(self) -> None:
        """Keep full PR/main acceptance and a distinct fast branch route.

        Args:
            None
        Returns:
            None
        """
        ci = (run_tests.ROOT / '.github' / 'workflows' / 'ci.yml').read_text(
            encoding='utf-8'
        )
        release = (run_tests.ROOT / '.github' / 'workflows' / 'release.yml').read_text(
            encoding='utf-8'
        )
        impact = (run_tests.ROOT / 'scripts' / 'ci_impact.py').read_text(
            encoding='utf-8'
        )
        for entry in ('ubuntu-latest', 'windows-latest', "'3.11'", "'3.13'"):
            self.assertIn(entry, impact)
        self.assertIn('fromJSON(needs.plan.outputs.matrix)', ci)
        self.assertIn('python scripts/run_tests.py --suite all', ci)
        self.assertIn('python scripts/run_tests.py --suite fast', ci)
        self.assertIn('workflow_dispatch:', ci)
        self.assertIn("mode == 'full'", ci)
        self.assertIn('  acceptance:', ci)
        self.assertIn('cancel-in-progress: true', ci)
        self.assertIn('github.event.pull_request.number || github.ref', ci)
        self.assertIn('  pull_request:', ci)
        self.assertNotIn("if: github.event_name != 'pull_request'", ci)
        self.assertIn('      - embeddedui', ci)
        self.assertIn('      - main', ci)
        self.assertIn('tests/gui_native_capture.py --view root_refresh', ci)
        self.assertIn('python scripts/run_tests.py --suite all', release)

    def test_conservative_ci_impact(self) -> None:
        """Use a small GUI group only for known views and full for shared work.

        Args:
            None
        Returns:
            None
        """
        root = run_tests.ROOT
        self.assertEqual(
            ci_impact.decide(['src/metor/ui/gui/views/root/panel.py'], root),
            ('fast', ('test_gui_contract', 'test_gui_root')),
        )
        self.assertEqual(ci_impact.decide(['docs/GLOSSARY.md'], root), ('fast', ()))
        for name in (
            'README.md',
            'src/metor/ui/gui/views/profiles/lifecycle.py',
            'src/metor/ui/terminal/chat/renderer/input.py',
            'src/metor/client/frontends.py',
            'src/metor/data/profile/catalog.py',
            'requirements/dev.txt',
            '.github/workflows/ci.yml',
            'unknown-path.py',
        ):
            self.assertEqual(ci_impact.decide([name], root), ('full', ()))
        self.assertEqual(ci_impact.decide([], root), ('full', ()))

    def test_output_is_bounded(self) -> None:
        """Limit captured text even if a test writes much more.

        Args:
            None
        Returns:
            None
        """
        buffer = run_tests.CappedOutput()
        self.assertEqual(
            buffer.write('x' * (run_tests.MAX_OUTPUT * 2)), run_tests.MAX_OUTPUT * 2
        )
        self.assertEqual(buffer.size, run_tests.MAX_OUTPUT)

    def test_standard_result_semantics_and_failfast(self) -> None:
        """Exercise failure, error, subtest, cleanup, xfail and xpass callbacks.

        Args:
            None
        Returns:
            None
        """
        visited: list[str] = []

        class Synthetic(unittest.TestCase):
            def test_failure(self) -> None:
                visited.append('failure')
                self.fail('secret=must-stay-private')

            def test_error(self) -> None:
                visited.append('error')
                raise ValueError('secret=must-stay-private')

            def test_subtest(self) -> None:
                visited.append('subtest')
                with self.subTest(secret='must-stay-private'):
                    self.fail('secret=must-stay-private')

            def test_cleanup(self) -> None:
                visited.append('cleanup')
                self.addCleanup(lambda: self.fail('secret=must-stay-private'))

            def test_after(self) -> None:
                visited.append('after')

            @unittest.expectedFailure
            def test_expected(self) -> None:
                self.fail('secret=must-stay-private')

            @unittest.expectedFailure
            def test_unexpected(self) -> None:
                pass

        for failing in ('test_failure', 'test_error', 'test_subtest', 'test_cleanup'):
            visited.clear()
            result = run_tests.TimedResult()
            result.failfast = True
            unittest.TestSuite([Synthetic(failing), Synthetic('test_after')]).run(
                result
            )
            self.assertEqual(visited, [failing.removeprefix('test_')])
            self.assertFalse(result.wasSuccessful())
            self.assertTrue(result.shouldStop)
            self.assertNotIn('must-stay-private', str(result.failures + result.errors))
            self.assertNotIn('must-stay-private', str(result.diagnostics))
            visited.clear()
            result = run_tests.TimedResult()
            unittest.TestSuite([Synthetic(failing), Synthetic('test_after')]).run(
                result
            )
            self.assertIn('after', visited)
            self.assertFalse(result.wasSuccessful())
        expected = run_tests.TimedResult()
        unittest.TestSuite([Synthetic('test_expected')]).run(expected)
        self.assertTrue(expected.wasSuccessful())
        self.assertEqual(expected.statuses[next(iter(expected.statuses))], 'xfail')
        unexpected = run_tests.TimedResult()
        unittest.TestSuite([Synthetic('test_unexpected')]).run(unexpected)
        self.assertFalse(unexpected.wasSuccessful())
        self.assertEqual(unexpected.statuses[next(iter(unexpected.statuses))], 'xpass')

    def test_subprocess_exit_and_safe_diagnostic(self) -> None:
        """Run a real child process over a disposable synthetic module.

        Args:
            None
        Returns:
            None
        """
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'test_synthetic.py').write_text(
                'import os, unittest\n'
                'class Example(unittest.TestCase):\n'
                '    def test_a(self):\n'
                '        os.write(1, b"credential=native-hidden\\n")\n'
                '        os.write(2, b"credential=native-hidden\\n")\n'
                '        self.fail("credential=hidden")\n'
                '    def test_b(self): print("AFTER_MARKER")\n',
                encoding='utf-8',
            )
            program = (
                'import sys; from pathlib import Path; from scripts import run_tests as r; '
                'r.TESTS=Path(sys.argv[1]); r.REPORT=r.TESTS/"report.txt"; '
                'r.FAST_MODULES=("test_synthetic",); r.INTEGRATION_MODULES=(); '
                'sys.exit(r.main(sys.argv[2:]))'
            )
            result = subprocess.run(
                [
                    sys.executable,
                    '-c',
                    program,
                    directory,
                    '--suite',
                    'fast',
                    '--failfast',
                ],
                cwd=run_tests.ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn('Ran 1/2', result.stdout)
            self.assertIn('AssertionError at', result.stdout)
            self.assertNotIn('credential=hidden', result.stdout)
            self.assertNotIn('credential=native-hidden', result.stdout)
            self.assertNotIn('credential=native-hidden', result.stderr)
            report = (root / 'report.txt').read_text(encoding='utf-8')
            self.assertNotIn('credential=hidden', report)
            self.assertIn('Incomplete: 1 selected cases', report)

    def test_abrupt_worker_exit_zero_is_rejected(self) -> None:
        """A child that bypasses result finalization cannot certify the suite.

        Args:
            None
        Returns:
            None
        """
        sink = io.StringIO()
        with redirect_stdout(sink):
            status = run_tests.supervised(
                [sys.executable, '-c', 'import os; os._exit(0)']
            )
        self.assertEqual(status, 1)
        self.assertIn('without a bounded, completed result', sink.getvalue())

    def test_fixture_skip_and_error_accounting(self) -> None:
        """Class fixture skips count as covered; fixture errors leave cases incomplete.

        Args:
            None
        Returns:
            None
        """

        class Skipped(unittest.TestCase):
            @classmethod
            def setUpClass(cls) -> None:
                raise unittest.SkipTest('Windows-native fixture')

            def test_one(self) -> None:
                self.fail('never reached')

        class Broken(unittest.TestCase):
            @classmethod
            def setUpClass(cls) -> None:
                raise RuntimeError('credential=hidden')

            def test_one(self) -> None:
                self.fail('never reached')

        status, output = self.invoke([Skipped('test_one')])
        self.assertEqual(status, 0)
        self.assertIn('skips=1', output)
        self.assertNotIn('Incomplete:', output)
        status, output = self.invoke([Broken('test_one')])
        self.assertEqual(status, 1)
        self.assertIn('Incomplete: 1', output)
        self.assertIn('Setup', output)
        self.assertNotIn('credential=hidden', output)

    def test_verified_sdk_rejection_and_independent_failure_budget(self) -> None:
        """Keep a typed negative outcome visible after many private skips.

        Args:
            None
        Returns:
            None
        """

        def skip_case(self: unittest.TestCase) -> None:
            raise unittest.SkipTest('Windows secret=private-skip')

        skip_methods = {f'test_skip_{index}': skip_case for index in range(12)}
        skipped = type(
            'ManySkipped',
            (unittest.TestCase,),
            {'__module__': 'test_run_tests', **skip_methods},
        )

        class Rejected(unittest.TestCase):
            def test_rejected(self) -> None:
                raise MetorRequestRejectedError(InternalErrorEvent())

        with patch.object(Rejected, '__module__', 'test_run_tests'):
            status, output = self.invoke(
                [skipped(name) for name in skip_methods] + [Rejected('test_rejected')]
            )
        self.assertEqual(status, 1)
        self.assertIn('MetorRequestRejectedError outcome=internal_error', output)
        self.assertIn('skips=12', output)
        self.assertIn('2 skip diagnostics omitted', output)
        self.assertNotIn('private-skip', output)
        report = run_tests.REPORT.read_text(encoding='utf-8')
        self.assertIn('MetorRequestRejectedError outcome=internal_error', report)
        self.assertNotIn('private-skip', report)

        counterfeit = type('MetorRequestRejectedError', (Exception,), {})
        self.assertEqual(run_tests.safe_category(counterfeit('secret')), 'Exception')
        self.assertIsNone(run_tests.safe_outcome(counterfeit('secret')))

    def test_safe_phase_categories_cover_setup_test_and_cleanup(self) -> None:
        """Report each failed lifecycle callback without serializing its value.

        Args:
            None
        Returns:
            None
        """

        class Phases(unittest.TestCase):
            def test_setup(self) -> None:
                raise RuntimeError('secret=test')

            def setUp(self) -> None:
                if self._testMethodName == 'test_setup_failure':
                    raise ValueError('secret=setup')
                if self._testMethodName == 'test_cleanup_failure':
                    self.addCleanup(lambda: self.fail('secret=cleanup'))

            def test_setup_failure(self) -> None:
                pass

            def test_cleanup_failure(self) -> None:
                pass

        result = run_tests.TimedResult()
        unittest.TestSuite(
            [
                Phases('test_setup_failure'),
                Phases('test_setup'),
                Phases('test_cleanup_failure'),
            ]
        ).run(result)
        self.assertEqual(result.error_count, 2)
        self.assertEqual(result.failure_count, 1)
        self.assertTrue(any(line.startswith('Setup ') for line in result.diagnostics))
        self.assertTrue(any(line.startswith('Test ') for line in result.diagnostics))
        self.assertTrue(any(line.startswith('Cleanup ') for line in result.diagnostics))
        self.assertNotIn('secret=', str(result.diagnostics))


class SupervisorTests(unittest.TestCase):
    """Exercise worker supervision using only short synthetic processes."""

    _PREFIX = (
        'import os,sys,time,subprocess\n'
        'from pathlib import Path\n'
        'from scripts import run_tests as runner\n'
        'report=Path(os.environ["METOR_TEST_REPORT"])\n'
        'marker=Path(os.environ["METOR_TEST_COMPLETION"])\n'
        'nonce=os.environ["METOR_TEST_NONCE"]\n'
    )

    def invoke_worker(
        self,
        body: str,
        *,
        timeout: float = 2.0,
        max_stdout: int = 1024,
        max_stderr: int = 1024,
    ) -> tuple[int, str, float]:
        """Run one disposable worker with a fresh report destination.

        Args:
            body: Synthetic worker statements after the fixed safe imports.
            timeout: Test-only whole-worker limit.
            max_stdout: Test-only stdout budget.
            max_stderr: Test-only stderr budget.
        Returns:
            Status, bounded console text and elapsed time.
        """
        with TemporaryDirectory() as directory:
            started = time.monotonic()
            sink = io.StringIO()
            with redirect_stdout(sink):
                status = run_tests.supervised(
                    [sys.executable, '-c', self._PREFIX + body],
                    timeout=timeout,
                    max_stdout=max_stdout,
                    max_stderr=max_stderr,
                    report_path=Path(directory) / 'report.txt',
                )
            return status, sink.getvalue(), time.monotonic() - started

    def invoke_with_child(
        self,
        *,
        detached: bool = False,
        ignore_term: bool = False,
        inherit_pipes: bool = False,
        root_hangs: bool = False,
        root_output_excess: bool = False,
        interrupt: bool = False,
        foreign: subprocess.Popen[bytes] | None = None,
    ) -> tuple[int, str, bool, bool]:
        """Observe and independently reap one disposable worker child.

        Args:
            detached: Give the child a separate session from the worker.
            ignore_term: Make the child require escalation on POSIX.
            inherit_pipes: Keep the worker's output pipes open in the child.
            root_hangs: Keep the root worker active until its supervisor deadline.
            root_output_excess: Trigger the bounded stdout guard after child startup.
            interrupt: Interrupt the supervisor after the child is registered.
            foreign: Preexisting, separately owned control process.
        Returns:
            Supervisor status, safe output, child liveness, and reader completion.
        """
        with TemporaryDirectory() as directory:
            root = Path(directory)
            marker, acknowledged = root / 'child.pid', root / 'acknowledged'
            child_program = (
                'import os,signal,time\n'
                'from pathlib import Path\n'
                + (
                    'signal.signal(signal.SIGTERM,signal.SIG_IGN)\n'
                    if ignore_term and os.name != 'nt'
                    else ''
                )
                + f'Path({str(marker)!r}).write_text(str(os.getpid()))\n'
                + 'time.sleep(30)\n'
            )
            options = (
                'creationflags=subprocess.DETACHED_PROCESS | '
                'subprocess.CREATE_NEW_PROCESS_GROUP'
                if detached and os.name == 'nt'
                else 'start_new_session=True'
                if detached
                else ''
            )
            streams = 'sys.stdout' if inherit_pipes else 'subprocess.DEVNULL'
            body = (
                f'subprocess.Popen([sys.executable,"-c",{child_program!r}],'
                f'stdout={streams},stderr={streams}'
                + (f',{options}' if options else '')
                + ')\n'
                + f'while not Path({str(acknowledged)!r}).exists(): time.sleep(.01)\n'
                + (
                    ('os.write(1,b"x"*10000)\n' if root_output_excess else '')
                    + 'time.sleep(30)\n'
                    if root_hangs or root_output_excess or interrupt
                    else 'report.write_text("safe report",encoding="utf-8")\n'
                    'runner.write_completion(marker,0,report,nonce)\n'
                )
            )
            output = io.StringIO()
            results: list[int] = []
            captures: list[test_supervision._StreamCapture] = []
            original_capture = test_supervision._StreamCapture

            def capture(limit: int) -> test_supervision._StreamCapture:
                item = original_capture(limit)
                captures.append(item)
                return item

            def run() -> None:
                original_sleep = time.sleep
                interrupted = False
                owner = threading.current_thread()

                def interrupt_once(seconds: float) -> None:
                    nonlocal interrupted
                    if (
                        interrupt
                        and not interrupted
                        and threading.current_thread() is owner
                        and acknowledged.exists()
                    ):
                        interrupted = True
                        raise KeyboardInterrupt
                    original_sleep(seconds)

                with redirect_stdout(output):
                    with patch.object(time, 'sleep', side_effect=interrupt_once):
                        results.append(
                            run_tests.supervised(
                                [sys.executable, '-c', self._PREFIX + body],
                                timeout=0.4 if root_hangs else 2.0,
                                max_stdout=128 if root_output_excess else 1024,
                                report_path=root / 'report.txt',
                            )
                        )

            child: psutil.Process | None = None
            created: float | None = None
            worker = threading.Thread(target=run, daemon=True)
            try:
                with patch.object(
                    test_supervision, '_StreamCapture', side_effect=capture
                ):
                    worker.start()
                    deadline = time.monotonic() + 5
                    while not marker.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue(marker.exists(), 'Synthetic child did not start')
                    child = psutil.Process(int(marker.read_text(encoding='ascii')))
                    created = child.create_time()
                    acknowledged.write_text('continue', encoding='ascii')
                    worker.join(12)
                self.assertFalse(
                    worker.is_alive(), 'Synthetic supervisor did not finish'
                )
                self.assertEqual(len(results), 1)
                if foreign is not None:
                    self.assertIsNone(foreign.poll(), 'Foreign process was terminated')
                assert child is not None and created is not None
                live = self._same_process_live(child, created)
                if sys.platform == 'linux' and not live:
                    try:
                        if child.create_time() == created:
                            self.assertNotEqual(
                                child.status(),
                                psutil.STATUS_ZOMBIE,
                                'Owned adopted child was not reaped',
                            )
                    except psutil.NoSuchProcess:
                        pass
                return (
                    results[0],
                    output.getvalue(),
                    live,
                    len(captures) == 2
                    and all(item.closed.is_set() for item in captures),
                )
            finally:
                acknowledged.write_text('continue', encoding='ascii')
                if child is None and marker.exists():
                    try:
                        child = psutil.Process(int(marker.read_text(encoding='ascii')))
                        created = child.create_time()
                    except (ValueError, psutil.Error):
                        pass
                if child is not None and created is not None:
                    if self._same_process_live(child, created):
                        child.kill()
                    try:
                        child.wait(timeout=2)
                    except (psutil.Error, psutil.TimeoutExpired):
                        pass
                worker.join(12)

    @staticmethod
    def _same_process_live(process: psutil.Process, created: float) -> bool:
        """Check liveness without treating a reused PID as the same child.

        Args:
            process: Process handle captured while the child was alive.
            created: Creation time captured before releasing the worker.
        Returns:
            True only for the original, still-running child.
        """
        try:
            return process.create_time() == created and process.status() not in (
                psutil.STATUS_DEAD,
                psutil.STATUS_ZOMBIE,
            )
        except psutil.NoSuchProcess:
            return False

    def test_complete_worker_preserves_status_and_report(self) -> None:
        """Accept only matching complete success and failure evidence.

        Args:
            None
        Returns:
            None
        """
        for status in (0, 7):
            body = (
                'report.write_text("safe report\\n",encoding="utf-8")\n'
                f'runner.write_completion(marker,{status},report,nonce)\n'
                'print("safe-summary")\n'
                f'sys.exit({status})\n'
            )
            actual, output, _elapsed = self.invoke_worker(body)
            self.assertEqual(actual, status)
            self.assertIn('safe-summary', output)

    def test_missing_or_invalid_completion_is_never_green(self) -> None:
        """Reject abrupt exits and a malformed completion record.

        Args:
            None
        Returns:
            None
        """
        for body in (
            'os._exit(0)\n',
            'os._exit(7)\n',
            'report.write_text("safe report",encoding="utf-8")\n'
            'marker.write_text("{",encoding="ascii")\n',
        ):
            status, output, _elapsed = self.invoke_worker(body)
            self.assertEqual(status, 1)
            self.assertIn('without a bounded, completed result', output)

    def test_stdout_and_stderr_are_limited_during_execution(self) -> None:
        """Drain both pipes while preventing unlimited or private output.

        Args:
            None
        Returns:
            None
        """
        for stream in (1, 2):
            body = f'os.write({stream},b"private-token"*10000)\ntime.sleep(10)\n'
            status, output, elapsed = self.invoke_worker(
                body, timeout=3, max_stdout=128, max_stderr=128
            )
            self.assertEqual(status, 1)
            self.assertIn('output-limit', output)
            self.assertNotIn('private-token', output)
            self.assertLess(elapsed, 3)

    def test_hanging_worker_and_inherited_pipe_end_bounded(self) -> None:
        """Stop a hung worker and a child that keeps its pipe handle open.

        Args:
            None
        Returns:
            None
        """
        status, output, elapsed = self.invoke_worker('time.sleep(10)\n', timeout=0.2)
        self.assertEqual(status, 1)
        self.assertIn('timeout', output)
        self.assertLess(elapsed, 4)
        body = (
            'subprocess.Popen([sys.executable,"-c","import time;time.sleep(10)"],'
            'stdout=sys.stdout,stderr=sys.stderr)\n'
            'report.write_text("safe report",encoding="utf-8")\n'
            'runner.write_completion(marker,0,report,nonce)\n'
        )
        status, output, elapsed = self.invoke_worker(body)
        self.assertEqual(status, 1)
        self.assertIn('process-left-running', output)
        self.assertLess(elapsed, 7)

    def test_live_children_are_cleaned_after_root_completion(self) -> None:
        """Confirm same-group and detached children actually exit after a report.

        Args:
            None
        Returns:
            None
        """
        cases = (
            ('pipe-holder', False, False, True),
            ('term-resistant', False, True, True),
            ('detached-devnull', True, False, False),
        )
        for label, detached, ignore_term, inherit_pipes in cases:
            with self.subTest(case=label):
                status, output, child_live, readers_done = self.invoke_with_child(
                    detached=detached,
                    ignore_term=ignore_term,
                    inherit_pipes=inherit_pipes,
                )
                self.assertEqual(status, 1)
                self.assertIn('process-left-running', output)
                self.assertFalse(child_live)
                self.assertTrue(readers_done)

    def test_hung_root_child_and_preexisting_foreign_process(self) -> None:
        """Stop owned children and refuse ambiguous Linux sibling ownership.

        Args:
            None
        Returns:
            None
        """
        status, output, child_live, readers_done = self.invoke_with_child(
            ignore_term=True,
            root_hangs=True,
        )
        self.assertEqual(status, 1)
        self.assertIn('timeout', output)
        self.assertFalse(child_live)
        self.assertTrue(readers_done)

        foreign = subprocess.Popen(
            [sys.executable, '-c', 'import time;time.sleep(30)'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            if sys.platform == 'linux':
                body = (
                    'report.write_text("safe report",encoding="utf-8")\n'
                    'runner.write_completion(marker,0,report,nonce)\n'
                )
                status, output, _elapsed = self.invoke_worker(body)
                self.assertEqual(status, 1)
                self.assertIn('could not start', output)
            else:
                status, output, child_live, readers_done = self.invoke_with_child(
                    ignore_term=True,
                    root_hangs=True,
                    foreign=foreign,
                )
                self.assertEqual(status, 1)
                self.assertIn('timeout', output)
                self.assertFalse(child_live)
                self.assertTrue(readers_done)
            self.assertIsNone(foreign.poll())
        finally:
            foreign.kill()
            foreign.wait(timeout=2)

    def test_output_limit_and_interrupt_clean_live_children(self) -> None:
        """Require confirmed child and reader exits on two supervisor aborts.

        Args:
            None
        Returns:
            None
        """
        for root_output_excess, interrupt, expected_status, reason in (
            (True, False, 1, 'output-limit'),
            (False, True, 130, 'interrupted'),
        ):
            with self.subTest(reason=reason):
                status, output, child_live, readers_done = self.invoke_with_child(
                    root_output_excess=root_output_excess,
                    interrupt=interrupt,
                )
                self.assertEqual(status, expected_status)
                self.assertIn(reason, output)
                self.assertFalse(child_live)
                self.assertTrue(readers_done)

    def test_unverifiable_lifetime_is_not_success(self) -> None:
        """Fail when ownership checks or final cleanup cannot be confirmed.

        Args:
            None
        Returns:
            None
        """
        lifetime = _WindowsLifetime if os.name == 'nt' else _PosixLifetime
        body = (
            'report.write_text("safe report",encoding="utf-8")\n'
            'runner.write_completion(marker,0,report,nonce)\n'
        )
        with patch.object(lifetime, 'live', side_effect=OSError('private identity')):
            status, output, _elapsed = self.invoke_worker(body)
        self.assertEqual(status, 1)
        self.assertIn('ownership-unconfirmed', output)
        self.assertNotIn('private identity', output)
        close_calls: list[bool] = []
        original_close = lifetime.close

        def observed_close(instance: _PosixLifetime | _WindowsLifetime) -> bool:
            close_calls.append(True)
            return original_close(instance)

        with (
            patch.object(lifetime, 'stop', side_effect=OSError('private cleanup')),
            patch.object(lifetime, 'close', observed_close),
        ):
            status, output, _elapsed = self.invoke_worker(body)
        self.assertEqual(status, 1)
        self.assertIn('ownership-unconfirmed', output)
        self.assertNotIn('private cleanup', output)
        self.assertEqual(close_calls, [True])

    def test_timeout_reports_only_a_verified_running_case(self) -> None:
        """Keep the active unittest ID when a real runner case stops progressing.

        Args:
            None
        Returns:
            None
        """
        with TemporaryDirectory() as directory:
            root = Path(directory)
            entered = root / 'entered.txt'
            (root / 'test_supervision_fixture.py').write_text(
                'import time,unittest\n'
                'from pathlib import Path\n'
                'class Example(unittest.TestCase):\n'
                '    def test_hang(self):\n'
                f'        Path({str(entered)!r}).write_text("entered",encoding="ascii")\n'
                '        time.sleep(60)\n',
                encoding='utf-8',
            )
            program = (
                'import os,sys\n'
                'from pathlib import Path\n'
                'from scripts import run_tests as runner\n'
                'runner.TESTS=Path(sys.argv[1])\n'
                'runner.REPORT=Path(os.environ["METOR_TEST_REPORT"])\n'
                'runner.FAST_MODULES=("test_supervision_fixture",)\n'
                'runner.INTEGRATION_MODULES=()\n'
                'os.environ["METOR_TEST_PROGRESS_OWNER"]=str(os.getpid())\n'
                'sys.exit(runner.main(["--suite","fast"]))\n'
            )
            sink = io.StringIO()
            real_clock = time.monotonic
            clock_started = False

            def after_test_start() -> float:
                """Expire the worker guard only after the test body has started.

                Args:
                    None
                Returns:
                    Controlled supervisor clock value.
                """
                nonlocal clock_started
                if not clock_started:
                    clock_started = True
                    return real_clock()
                return real_clock() + (31.0 if entered.exists() else 0.0)

            with (
                redirect_stdout(sink),
                patch.object(test_supervision, '_CLOCK', side_effect=after_test_start),
            ):
                status = run_tests.supervised(
                    [sys.executable, '-c', program, directory],
                    timeout=30.0,
                    report_path=root / 'report.txt',
                )
            self.assertTrue(entered.exists(), 'Synthetic test body did not start')
            self.assertEqual(status, 1)
            self.assertIn(
                'Last running test: test_supervision_fixture.Example.test_hang',
                sink.getvalue(),
            )
            self.assertIn('timeout', sink.getvalue())

    def test_keyboard_interrupt_stops_owned_worker(self) -> None:
        """Treat a user interrupt as an abort and stop its live child.

        Args:
            None
        Returns:
            None
        """
        original_sleep = time.sleep
        interrupted = False

        def interrupt_once(seconds: float) -> None:
            nonlocal interrupted
            if not interrupted:
                interrupted = True
                raise KeyboardInterrupt
            original_sleep(seconds)

        with patch.object(run_tests.time, 'sleep', side_effect=interrupt_once):
            status, output, elapsed = self.invoke_worker('time.sleep(10)\n')
        self.assertEqual(status, 130)
        self.assertIn('interrupted', output)
        self.assertLess(elapsed, 4)

    def test_unwritable_report_path_fails_explicitly(self) -> None:
        """A completed old report cannot mask a current write failure.

        Args:
            None
        Returns:
            None
        """
        with TemporaryDirectory() as directory:
            blocker = Path(directory) / 'blocker'
            blocker.write_text('not a directory', encoding='utf-8')
            sink = io.StringIO()
            with redirect_stdout(sink):
                status = run_tests.supervised(
                    [
                        sys.executable,
                        str(run_tests.ROOT / 'scripts' / 'run_tests.py'),
                        '--suite',
                        'fast',
                        '--module',
                        'test_run_tests',
                        '--match',
                        'test_output_is_bounded',
                    ],
                    timeout=5,
                    report_path=blocker / 'report.txt',
                )
            self.assertEqual(status, 1)
            self.assertIn('Test report could not be written', sink.getvalue())
            self.assertIn('without a bounded, completed result', sink.getvalue())

    def test_quality_action_preserves_direct_child_status(self) -> None:
        """Execute the actual composite shell body for both child outcomes.

        Args:
            None
        Returns:
            None
        """
        action = (
            run_tests.ROOT / '.github' / 'actions' / 'python-quality' / 'action.yml'
        ).read_text(encoding='utf-8')
        body = dedent(
            action.split('    - name: Run Tests\n', 1)[1].split('      run: |\n', 1)[1]
        )
        self.assertNotIn(' | tee ', body)
        bash = shutil.which('bash')
        if sys.platform == 'win32':
            git_exec = subprocess.run(
                ['git', '--exec-path'],
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            bash = str(Path(git_exec).parents[2] / 'bin' / 'bash.exe')
            self.assertTrue(Path(bash).is_file())
        elif bash is None:
            self.skipTest('Bash unavailable for composite action test')
        for status in (0, 7):
            command = f'(exit {status})'
            shell = body.replace('${{ inputs.test-command }}', command)
            completed = subprocess.run(
                [bash, '--noprofile', '--norc', '-e', '-o', 'pipefail', '-c', shell],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, status)
        annotation_fails = 'echo() { return 9; }\n' + body.replace(
            '${{ inputs.test-command }}', '(exit 7)'
        )
        completed = subprocess.run(
            [
                bash,
                '--noprofile',
                '--norc',
                '-e',
                '-o',
                'pipefail',
                '-c',
                annotation_fails,
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 7)


if __name__ == '__main__':
    unittest.main()
