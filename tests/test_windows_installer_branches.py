"""Execute the Windows offline installer against controlled native interpreter candidates."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
import venv

from scripts.release.bundle import build_install_windows_script


@unittest.skipUnless(os.name == 'nt', 'native Windows cmd.exe required')
class WindowsInstallerBranchTests(unittest.TestCase):
    """Check actual command discovery, verification order, and refusal of existing environments."""

    probe: Path

    @classmethod
    def setUpClass(cls) -> None:
        """Compile one inert native command probe in a disposable test directory."""
        temporary = TemporaryDirectory(prefix='metor-cmd-probe-')
        cls.addClassCleanup(temporary.cleanup)
        root = Path(temporary.name)
        cls.probe = root / 'probe.exe'
        source = root / 'probe.cs'
        source.write_text(
            'using System;\nusing System.IO;\nusing System.Diagnostics;\n'
            'class Probe { static int Main(string[] args) {\n'
            '  string path = Process.GetCurrentProcess().MainModule.FileName;\n'
            '  string name = Path.GetFileNameWithoutExtension(path);\n'
            '  File.AppendAllText(Environment.GetEnvironmentVariable("METOR_TRACE"), '
            'path + "\\t" + string.Join("\\t", args) + Environment.NewLine);\n'
            '  if (Array.IndexOf(args, "--target-only") >= 0)\n'
            '    return int.Parse(Environment.GetEnvironmentVariable("METOR_" + name.ToUpperInvariant()));\n'
            '  return Array.IndexOf(args, "venv") >= 0 ? 23 : 0;\n'
            '} }\n',
            encoding='ascii',
        )
        compiler = root / 'compile.ps1'
        compiler.write_text(
            "$ErrorActionPreference = 'Stop'\n"
            'Add-Type -LiteralPath $args[0] -OutputAssembly $args[1] -OutputType ConsoleApplication\n',
            encoding='ascii',
        )
        powershell = (
            Path(os.environ['SystemRoot'])
            / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        )
        subprocess.run(
            [
                str(powershell),
                '-NoProfile',
                '-NonInteractive',
                '-File',
                str(compiler),
                str(source),
                str(cls.probe),
            ],
            check=True,
            capture_output=True,
            timeout=45,
        )

    def _selection(
        self,
        py: int | None,
        python: int | None,
        *,
        archive_on_path: bool = True,
        alias_root: bool = False,
    ) -> tuple[str, list[tuple[str, ...]]]:
        """Run the installer with archive shadows and two external PATH candidates."""
        with TemporaryDirectory(prefix='metor candidate ! ') as directory:
            root = Path(directory)
            if alias_root:
                root = self._alternate_spelling(root)
            bundle = root / 'Bundle %METOR_EXPAND% !'
            external = root / 'External %METOR_EXPAND% !'
            nested = bundle / 'nested'
            nested.mkdir(parents=True)
            external.mkdir()
            verifier = bundle / 'verify_bundle.py'
            verifier.write_text(
                '# Inert verifier path for the native probe.\n', encoding='ascii'
            )
            trace = root / 'trace.txt'
            marker = root / 'cmd-ran'
            (bundle / 'install.cmd').write_text(
                build_install_windows_script(), encoding='utf-8'
            )
            (bundle / 'py.cmd').write_text(
                '@echo ran>"%METOR_MARKER%"\n', encoding='ascii'
            )
            shutil.copyfile(self.probe, bundle / 'python.exe')
            shutil.copyfile(self.probe, nested / 'py.exe')
            for name, status in (('py', py), ('python', python)):
                if status is not None:
                    shutil.copyfile(self.probe, external / (name + '.exe'))
            search = [bundle, nested, external] if archive_on_path else [external]
            environment = {
                **os.environ,
                'PATH': os.pathsep.join(map(str, search)),
                'METOR_TRACE': str(trace),
                'METOR_MARKER': str(marker),
                'METOR_EXPAND': 'WRONG',
                'METOR_PY': str(py or 0),
                'METOR_PYTHON': str(python or 0),
            }
            process = subprocess.run(
                [os.environ['COMSPEC'], '/d', '/c', 'install.cmd'],
                cwd=bundle,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertNotEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertFalse(marker.exists(), 'Archive-root py.cmd was executed')
            rows = (
                [line.split('\t') for line in trace.read_text().splitlines()]
                if trace.exists()
                else []
            )
            calls: list[tuple[str, ...]] = []
            for path, *args in rows:
                observed = Path(path)
                self.assertIn(observed.name, ('py.exe', 'python.exe'))
                self.assertTrue(
                    observed.parent.samefile(external)
                    and observed.samefile(external / observed.name),
                    f'Unexpected {observed.name} location: bundle root={observed.parent.samefile(bundle)}, '
                    f'bundle subdirectory={observed.parent.samefile(nested)}',
                )
                selector = (
                    [f'-{sys.version_info.major}.{sys.version_info.minor}']
                    if observed.stem == 'py'
                    else []
                )
                if 'venv' in args:
                    self.assertEqual(args[:-1], [*selector, '-I', '-m', 'venv'])
                    target = Path(args[-1])
                    self.assertEqual(target.name, '.venv')
                    self.assertTrue(
                        target.parent.samefile(bundle)
                        and target.samefile(bundle / '.venv')
                    )
                else:
                    verify_args = args[:-1] if args[-1] == '--target-only' else args
                    self.assertEqual(verify_args[:-2], [*selector, '-I', '-S'])
                    script = Path(verify_args[-2])
                    self.assertEqual(script.name, verifier.name)
                    self.assertTrue(
                        script.parent.samefile(bundle) and script.samefile(verifier)
                    )
                    self.assertTrue(Path(verify_args[-1]).samefile(bundle))
                calls.append((Path(path).stem, *args))
            return process.stdout + process.stderr, calls

    @staticmethod
    def _alternate_spelling(path: Path) -> Path:
        """Use a real DOS short path when available, or a distinct path to the same directory."""
        import ctypes
        from ctypes import wintypes

        get_short = ctypes.windll.kernel32.GetShortPathNameW
        get_short.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        get_short.restype = wintypes.DWORD
        size = get_short(str(path), None, 0)
        if size:
            buffer = ctypes.create_unicode_buffer(size)
            if 0 < get_short(str(path), buffer, size) < size:
                short = Path(buffer.value)
                if short != path and short.samefile(path):
                    return short
        detour = path / 'path-spelling'
        detour.mkdir()
        return detour / '..'

    def test_alternate_directory_spelling_preserves_external_executable_and_arguments(
        self,
    ) -> None:
        """Aliases for a trusted temporary root preserve real process and argument identities."""
        _, calls = self._selection(0, 0, alias_root=True)
        self.assertEqual(calls[-1][0], 'py')
        self.assertIn('venv', calls[-1])

    def test_matching_launcher_wins_and_unavailable_launcher_falls_back(self) -> None:
        """Probe the requested Python minor before fallback, then verify before venv creation."""
        target = f'-{sys.version_info.major}.{sys.version_info.minor}'
        for launch_status, expected in ((0, 'py'), (1, 'python'), (None, 'python')):
            with self.subTest(launcher=launch_status):
                _, calls = self._selection(
                    launch_status, 0, archive_on_path=launch_status is None
                )
                self.assertTrue(calls)
                self.assertIn('--target-only', calls[0])
                if launch_status is not None:
                    self.assertEqual(calls[0][:2], ('py', target))
                self.assertEqual(calls[-2][0], expected)
                self.assertNotIn('--target-only', calls[-2])
                self.assertEqual(calls[-1][0], expected)
                self.assertIn('venv', calls[-1])

    def test_no_external_match_never_uses_bundle_commands(self) -> None:
        """Neither a failed probe nor an empty external PATH falls back to archive contents."""
        for status in (1, None):
            with self.subTest(status=status):
                output, calls = self._selection(status, status)
                self.assertIn('No interpreter matches', output)
                self.assertTrue(all('--target-only' in call for call in calls))

    def test_existing_venv_preserved_without_running_its_pth(self) -> None:
        """Refuse before an installed Python can execute code from its site packages."""
        with TemporaryDirectory(prefix='metor installed ! ') as directory:
            bundle = Path(directory)
            environment = bundle / '.venv'
            venv.EnvBuilder(with_pip=False).create(environment)
            marker = bundle / 'pth-executed'
            hook = environment / 'Lib/site-packages/marker.pth'
            text = f'import pathlib; pathlib.Path({str(marker)!r}).touch()\n'
            hook.write_text(text, encoding='utf-8')
            (bundle / 'install.cmd').write_text(
                build_install_windows_script(), encoding='utf-8'
            )
            process = subprocess.run(
                [os.environ['COMSPEC'], '/d', '/c', 'install.cmd'],
                cwd=bundle,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertNotEqual(process.returncode, 0)
            self.assertIn('fresh directory', process.stderr)
            self.assertFalse(marker.exists())
            self.assertEqual(hook.read_text(encoding='utf-8'), text)
