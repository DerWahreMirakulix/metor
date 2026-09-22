"""Native cmd.exe coverage for release-installer interpreter selection branches."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
import venv

from scripts.release.bundle import build_install_windows_script


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
    ) -> tuple[subprocess.CompletedProcess[str], tuple[str, ...]]:
        """Runs one exact generated installer through controlled cmd resolution.

        Args:
            py_target: ``py`` probe status, or None when the launcher is absent.
            python_target: ``python`` probe status, or None when absent.
        Returns:
            tuple: Completed cmd process and recorded command trace.
        """
        with TemporaryDirectory(prefix='metor installer ! ') as directory:
            bundle = Path(directory) / 'Bundle With Spaces !'
            commands = bundle / 'commands'
            commands.mkdir(parents=True)
            installer = bundle / 'install.cmd'
            installer.write_text(build_install_windows_script(), encoding='utf-8')
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
            result = subprocess.run(
                [environment['COMSPEC'], '/d', '/c', 'call install.cmd'],
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
            return result, lines

    def test_launcher_failure_falls_back_to_matching_python(self) -> None:
        """A present but unsuitable py launcher cannot mask a suitable python."""
        result, lines = self._selection_case(1, 0)
        self.assertNotEqual(result.returncode, 0)
        diagnostics = (
            f'returncode={result.returncode}; args={result.args!r}; lines={lines!r}\n'
            + result.stdout
            + result.stderr
        )
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

    def test_matching_launcher_wins_and_missing_launcher_uses_python(self) -> None:
        """Both supported selection orders reach only the matching interpreter."""
        _result, launcher_lines = self._selection_case(0, 0)
        self.assertTrue(
            any(' -m venv ' in f' {line} ' for line in launcher_lines),
            f'returncode={_result.returncode}; output={_result.stdout + _result.stderr!r}; '
            f'lines={launcher_lines!r}',
        )
        self.assertFalse(any(line.startswith('python ') for line in launcher_lines))
        _result, python_lines = self._selection_case(None, 0)
        self.assertTrue(any(line.startswith('python ') for line in python_lines))
        self.assertTrue(any(' -m venv ' in f' {line} ' for line in python_lines))

    def test_no_matching_interpreter_fails_without_creating_environment(self) -> None:
        """Missing or unsuitable candidates fail closed before the venv mutation."""
        result, lines = self._selection_case(1, 1)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            'No interpreter matches this bundle target.',
            result.stdout + result.stderr,
            f'returncode={result.returncode}; lines={lines!r}',
        )
        self.assertFalse(any(' -m venv ' in f' {line} ' for line in lines))

    def test_existing_environment_is_preserved_for_both_target_outcomes(self) -> None:
        """A complete existing venv is reused only after its same interpreter verifies it."""
        for target_status in (0, 1):
            with (
                self.subTest(target_status=target_status),
                TemporaryDirectory(prefix='metor existing ! ') as directory,
            ):
                bundle = Path(directory) / 'Existing Venv With Spaces !'
                bundle.mkdir()
                (bundle / 'install.cmd').write_text(
                    build_install_windows_script(), encoding='utf-8'
                )
                (bundle / 'verify_bundle.py').write_text(
                    'import os, sys\n'
                    "if '--target-only' in sys.argv:\n"
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
                result = subprocess.run(
                    [
                        environment.get('COMSPEC', 'C:\\Windows\\System32\\cmd.exe'),
                        '/d',
                        '/c',
                        'call install.cmd',
                    ],
                    cwd=bundle,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(sentinel.is_file())
                if target_status:
                    self.assertIn('incompatible or incomplete', result.stdout)
                else:
                    self.assertNotIn('incompatible or incomplete', result.stdout)


if __name__ == '__main__':
    unittest.main()
