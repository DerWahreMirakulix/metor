"""Native cmd.exe coverage for release-installer interpreter selection branches."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import NamedTuple
import unittest
import venv

from scripts.release.bundle import build_install_windows_script


class InstallerEvidence(NamedTuple):
    """Captured native batch execution evidence for assertion diagnostics."""

    result: subprocess.CompletedProcess[str]
    trace: tuple[str, ...]
    batch: str
    cwd: str
    argv: tuple[str, ...]
    environment: tuple[tuple[str, str], ...]

    def diagnostic(self) -> str:
        """Formats all evidence needed to reproduce a failed native branch.

        Args:
            None

        Returns:
            str: Complete non-secret process and generated-batch evidence.
        """
        return (
            f'cwd={self.cwd!r}\n'
            f'argv={self.argv!r}\n'
            f'environment={dict(self.environment)!r}\n'
            f'returncode={self.result.returncode}\n'
            f'trace={self.trace!r}\n'
            f'stdout={self.result.stdout!r}\n'
            f'stderr={self.result.stderr!r}\n'
            f'install.cmd:\n{self.batch}'
        )


@unittest.skipUnless(os.name == 'nt', 'native Windows cmd.exe required')
@unittest.skipIf(
    'inkscape' in sys.executable.lower(),
    'embedded Inkscape Python cannot provide a standard Windows test environment',
)
class WindowsInstallerBranchTests(unittest.TestCase):
    """Executes the generated batch file with controlled interpreter front doors."""

    def _wrapper(self, name: str, target_variable: str, *, launcher: bool) -> str:
        """Builds one cmd shim that records probes and stops before installation.

        Args:
            name: Human-readable command identity written to the trace.
            target_variable: Environment variable controlling target-probe success.
            launcher: Whether the command includes a leading ``-3.x`` selector.
        Returns:
            str: Complete batch wrapper source.
        """
        target_arg = '4' if launcher else '3'
        venv_test = (
            'if "%~2"=="-m" if "%~3"=="venv" exit /b 23'
            if launcher
            else 'if "%~1"=="-m" if "%~2"=="venv" exit /b 23'
        )
        return (
            '@echo off\n'
            f'>>"%METOR_TEST_LOG%" echo {name} %*\n'
            f'if "%~{target_arg}"=="--target-only" exit /b %{target_variable}%\n'
            f'{venv_test}\n'
            'exit /b 0\n'
        )

    def _selection_case(
        self, py_target: int | None, python_target: int | None
    ) -> InstallerEvidence:
        """Runs one exact generated installer through controlled cmd resolution.

        Args:
            py_target: ``py`` probe status, or None when the launcher is absent.
            python_target: ``python`` probe status, or None when absent.
        Returns:
            InstallerEvidence: Exact process inputs, outputs, batch, and command trace.
        """
        with TemporaryDirectory(prefix='metor installer ! ') as directory:
            bundle = Path(directory) / 'Bundle With Spaces !'
            commands = bundle / 'commands'
            commands.mkdir(parents=True)
            installer = bundle / 'install.cmd'
            batch = build_install_windows_script()
            installer.write_text(batch, encoding='utf-8')
            (bundle / 'verify_bundle.py').write_text('', encoding='utf-8')
            log = bundle / 'selection.log'
            if py_target is not None:
                (commands / 'py.cmd').write_text(
                    self._wrapper('py', 'METOR_PY_TARGET', launcher=True),
                    encoding='utf-8',
                )
            if python_target is not None:
                (commands / 'python.cmd').write_text(
                    self._wrapper('python', 'METOR_PYTHON_TARGET', launcher=False),
                    encoding='utf-8',
                )
            environment = dict(os.environ)
            environment.update(
                {
                    'COMSPEC': 'C:\\Windows\\System32\\cmd.exe',
                    'PATH': str(commands)
                    + os.pathsep
                    + str(
                        Path(environment.get('SystemRoot', 'C:\\Windows')) / 'System32'
                    ),
                    'PATHEXT': '.COM;.EXE;.BAT;.CMD',
                    'SystemRoot': environment.get('SystemRoot', 'C:\\Windows'),
                    'METOR_TEST_LOG': str(log),
                    'METOR_PY_TARGET': str(py_target or 0),
                    'METOR_PYTHON_TARGET': str(python_target or 0),
                }
            )
            argv = (environment['COMSPEC'], '/d', '/c', 'call install.cmd')
            result = subprocess.run(
                argv,
                cwd=bundle,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
            )
            lines = (
                tuple(log.read_text(encoding='utf-8').splitlines())
                if log.exists()
                else ()
            )
            evidence_environment = tuple(
                (name, environment[name])
                for name in (
                    'COMSPEC',
                    'PATH',
                    'PATHEXT',
                    'SystemRoot',
                    'METOR_TEST_LOG',
                    'METOR_PY_TARGET',
                    'METOR_PYTHON_TARGET',
                )
            )
            return InstallerEvidence(
                result=result,
                trace=lines,
                batch=batch,
                cwd=str(bundle),
                argv=argv,
                environment=evidence_environment,
            )

    def test_launcher_failure_falls_back_to_matching_python(self) -> None:
        """A present but unsuitable py launcher cannot mask a suitable python."""
        evidence = self._selection_case(1, 0)
        result, lines = evidence.result, evidence.trace
        self.assertNotEqual(result.returncode, 0)
        diagnostics = evidence.diagnostic()
        self.assertTrue(
            any('--target-only' in line for line in lines if line.startswith('py ')),
            diagnostics,
        )
        self.assertTrue(
            any(
                '--target-only' in line for line in lines if line.startswith('python ')
            ),
            diagnostics,
        )
        self.assertTrue(
            any(
                ' -m venv ' in f' {line} '
                for line in lines
                if line.startswith('python ')
            ),
            diagnostics,
        )
        self.assertFalse(
            any(' -m venv ' in f' {line} ' for line in lines if line.startswith('py ')),
            diagnostics,
        )

    def test_matching_launcher_wins_and_missing_launcher_uses_python(self) -> None:
        """Both supported selection orders reach only the matching interpreter."""
        launcher = self._selection_case(0, 0)
        launcher_result, launcher_lines = launcher.result, launcher.trace
        self.assertNotEqual(launcher_result.returncode, 0, launcher.diagnostic())
        self.assertTrue(
            any(' -m venv ' in f' {line} ' for line in launcher_lines),
            launcher.diagnostic(),
        )
        self.assertFalse(
            any(line.startswith('python ') for line in launcher_lines),
            launcher.diagnostic(),
        )
        self.assertNotIn(
            'No interpreter matches this bundle target.',
            launcher_result.stdout + launcher_result.stderr,
            launcher.diagnostic(),
        )
        python = self._selection_case(None, 0)
        python_result, python_lines = python.result, python.trace
        self.assertNotEqual(python_result.returncode, 0, python.diagnostic())
        self.assertTrue(
            any(line.startswith('python ') for line in python_lines),
            python.diagnostic(),
        )
        self.assertTrue(
            any(' -m venv ' in f' {line} ' for line in python_lines),
            python.diagnostic(),
        )

    def test_no_matching_interpreter_fails_without_creating_environment(self) -> None:
        """Missing or unsuitable candidates fail closed before the venv mutation."""
        evidence = self._selection_case(1, 1)
        result, lines = evidence.result, evidence.trace
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            'No interpreter matches this bundle target.',
            result.stdout + result.stderr,
            evidence.diagnostic(),
        )
        self.assertFalse(
            any(' -m venv ' in f' {line} ' for line in lines),
            evidence.diagnostic(),
        )

    def test_existing_environment_is_preserved_for_both_target_outcomes(self) -> None:
        """A complete existing venv is reused only after its same interpreter verifies it."""
        for target_status in (0, 1):
            with (
                self.subTest(target_status=target_status),
                TemporaryDirectory(prefix='metor existing ! ') as directory,
            ):
                bundle = Path(directory) / 'Existing Venv With Spaces !'
                bundle.mkdir()
                batch = build_install_windows_script()
                (bundle / 'install.cmd').write_text(batch, encoding='utf-8')
                argument_log = bundle / 'received-arguments.jsonl'
                (bundle / 'verify_bundle.py').write_text(
                    'import json, os, pathlib, sys\n'
                    'args = sys.argv[1:]\n'
                    "with pathlib.Path(os.environ['METOR_ARGUMENT_LOG']).open('a', encoding='utf-8') as handle:\n"
                    "    handle.write(json.dumps(args) + '\\n')\n"
                    'if len(args) not in (1, 2):\n'
                    '    raise SystemExit(91)\n'
                    'if pathlib.Path(args[0]).resolve() != pathlib.Path(__file__).parent.resolve():\n'
                    '    raise SystemExit(92)\n'
                    'if len(args) == 2:\n'
                    "    if args[1] != '--target-only':\n"
                    '        raise SystemExit(93)\n'
                    "    raise SystemExit(int(os.environ['METOR_EXISTING_TARGET']))\n",
                    encoding='utf-8',
                )
                venv.EnvBuilder(with_pip=False).create(bundle / '.venv')
                venv_python = bundle / '.venv' / 'Scripts' / 'python.exe'
                if not venv_python.is_file():
                    self.skipTest('host Windows Python cannot create a standard venv')
                probe = subprocess.run(
                    [str(venv_python), '-c', 'print("ready")'],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(
                    probe.returncode,
                    0,
                    probe.stdout + probe.stderr,
                )
                sentinel = bundle / '.venv' / 'preserved.txt'
                sentinel.write_text('owned\n', encoding='utf-8')
                environment = dict(os.environ)
                environment['METOR_EXISTING_TARGET'] = str(target_status)
                environment['METOR_ARGUMENT_LOG'] = str(argument_log)
                argv = (
                    environment.get('COMSPEC', 'C:\\Windows\\System32\\cmd.exe'),
                    '/d',
                    '/c',
                    'call install.cmd',
                )
                result = subprocess.run(
                    argv,
                    cwd=bundle,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                evidence = InstallerEvidence(
                    result=result,
                    trace=(),
                    batch=batch,
                    cwd=str(bundle),
                    argv=argv,
                    environment=(
                        ('COMSPEC', argv[0]),
                        ('PATH', environment.get('PATH', '')),
                        ('PATHEXT', environment.get('PATHEXT', '')),
                        ('SystemRoot', environment.get('SystemRoot', '')),
                        ('METOR_EXISTING_TARGET', str(target_status)),
                    ),
                )
                self.assertNotEqual(
                    result.returncode,
                    0,
                    evidence.diagnostic(),
                )
                self.assertTrue(sentinel.is_file(), evidence.diagnostic())
                received_arguments = [
                    json.loads(line)
                    for line in argument_log.read_text(encoding='utf-8').splitlines()
                ]
                self.assertGreaterEqual(
                    len(received_arguments), 1, evidence.diagnostic()
                )
                self.assertEqual(
                    received_arguments[0][1:],
                    ['--target-only'],
                    evidence.diagnostic(),
                )
                self.assertEqual(
                    Path(received_arguments[0][0]).resolve(),
                    bundle.resolve(),
                    evidence.diagnostic(),
                )
                if target_status:
                    self.assertEqual(len(received_arguments), 1, evidence.diagnostic())
                    self.assertIn(
                        'incompatible or incomplete',
                        result.stdout,
                        evidence.diagnostic(),
                    )
                else:
                    self.assertEqual(len(received_arguments), 2, evidence.diagnostic())
                    self.assertEqual(
                        received_arguments[1],
                        [received_arguments[0][0]],
                        evidence.diagnostic(),
                    )
                    self.assertNotIn(
                        'incompatible or incomplete',
                        result.stdout,
                        evidence.diagnostic(),
                    )


if __name__ == '__main__':
    unittest.main()
