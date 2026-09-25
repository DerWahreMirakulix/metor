"""Contract tests for the bounded, fail-closed unittest runner."""

from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from textwrap import dedent
import time
import unittest
from typing import cast
from unittest.mock import Mock, patch

from scripts import ci_impact, run_tests
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
        self.assertIn('stream-open', output)
        self.assertLess(elapsed, 7)

    def test_timeout_reports_only_a_verified_running_case(self) -> None:
        """Keep the active unittest ID when a real runner case stops progressing.

        Args:
            None
        Returns:
            None
        """
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'test_supervision_fixture.py').write_text(
                'import time,unittest\n'
                'class Example(unittest.TestCase):\n'
                '    def test_hang(self): time.sleep(10)\n',
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
            with redirect_stdout(sink):
                status = run_tests.supervised(
                    [sys.executable, '-c', program, directory],
                    timeout=2.0,
                    report_path=root / 'report.txt',
                )
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
        if shutil.which('bash') is None:
            self.skipTest('Bash unavailable for composite action test')
        for status in (0, 7):
            command = f'(exit {status})'
            shell = body.replace('${{ inputs.test-command }}', command)
            completed = subprocess.run(
                ['bash', '-e', '-o', 'pipefail', '-c', shell],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, status)
        annotation_fails = 'echo() { return 9; }\n' + body.replace(
            '${{ inputs.test-command }}', '(exit 7)'
        )
        completed = subprocess.run(
            ['bash', '-e', '-o', 'pipefail', '-c', annotation_fails],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 7)


if __name__ == '__main__':
    unittest.main()
