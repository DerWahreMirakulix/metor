"""Exercise conservative CI impact decisions against actual Git commits."""

from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import ci_impact


class CiImpactTests(unittest.TestCase):
    """Require complete, regular-file diffs before selecting a fast branch check."""

    def setUp(self) -> None:
        """Create a disposable repository independent of local Git settings.

        Args:
            None
        Returns:
            None
        """
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'CI impact test')
        self.git('config', 'user.email', 'impact@example.invalid')

    def git(self, *arguments: str, input_bytes: bytes | None = None) -> str:
        """Run a Git command in only the disposable repository.

        Args:
            *arguments: Git command arguments.
            input_bytes: Optional bytes for standard input.
        Returns:
            Decoded standard output.
        """
        result = subprocess.run(
            ['git', *arguments],
            cwd=self.root,
            input=input_bytes,
            capture_output=True,
            check=True,
        )
        return result.stdout.decode('utf-8').strip()

    def write(self, name: str, content: str) -> None:
        """Write a regular candidate file under the disposable root.

        Args:
            name: Repository-relative file name.
            content: Harmless fixture text.
        Returns:
            None
        """
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')

    def commit(self) -> str:
        """Commit all staged changes and return the exact commit ID.

        Args:
            None
        Returns:
            New commit ID.
        """
        self.git('add', '-A')
        self.git('commit', '-qm', 'fixture')
        return self.git('rev-parse', 'HEAD')

    def classify(self, base: str, head: str) -> tuple[str, tuple[str, ...]]:
        """Apply the production diff parser and impact mapping together.

        Args:
            base: Previous fixture commit.
            head: Candidate fixture commit.
        Returns:
            Conservative CI mode and selected modules.
        """
        paths = ci_impact.changed_regular_paths(base, head, self.root)
        return ci_impact.decide(paths or [], self.root)

    def install_plan_scripts(self) -> None:
        """Copy the actual plan entrypoint and inventory into the Git fixture.

        Args:
            None
        Returns:
            None
        """
        source = Path(ci_impact.__file__).resolve().parent
        destination = self.root / 'scripts'
        destination.mkdir()
        for name in ('ci_impact.py', 'test_inventory.py'):
            shutil.copyfile(source / name, destination / name)

    def invoke_isolated_plan(
        self, *options: str, direct: bool = False
    ) -> tuple[int, dict[str, str], str]:
        """Run the real planner with site and checkout packages unavailable.

        Args:
            *options: Planner mode or diff references.
            direct: Invoke the script path instead of the module entrypoint.
        Returns:
            Exit status, parsed GitHub output, and process output.
        """
        output = self.root / '.git' / 'plan-output.txt'
        output.unlink(missing_ok=True)
        target = ['scripts/ci_impact.py'] if direct else ['-m', 'scripts.ci_impact']
        environment = os.environ.copy()
        environment.pop('PYTHONPATH', None)
        environment['PYTHONDONTWRITEBYTECODE'] = '1'
        result = subprocess.run(
            [
                sys.executable,
                '-S',
                *target,
                *options,
                '--github-output',
                str(output),
            ],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        entries = (
            dict(
                line.split('=', 1)
                for line in output.read_text(encoding='utf-8').splitlines()
            )
            if output.exists()
            else {}
        )
        return result.returncode, entries, result.stdout + result.stderr

    def test_isolated_plan_entrypoints_and_verified_diff(self) -> None:
        """A checkout-only Python plans full and fast paths without site packages.

        Args:
            None
        Returns:
            None
        """
        self.install_plan_scripts()
        panel = 'src/metor/ui/gui/views/root/panel.py'
        core = 'src/metor/core/tor.py'
        self.write(panel, 'before')
        self.write(core, 'before')
        base = self.commit()
        expected_matrix = {
            ('ubuntu-latest', '3.11'),
            ('ubuntu-latest', '3.13'),
            ('windows-latest', '3.11'),
            ('windows-latest', '3.13'),
        }
        for direct in (False, True):
            with self.subTest(entrypoint='script' if direct else 'module'):
                status, entries, output = self.invoke_isolated_plan(
                    '--full', direct=direct
                )
                self.assertEqual(status, 0, output)
                self.assertEqual(entries['mode'], 'full')
                self.assertEqual(entries['modules'], '')
                self.assertEqual(
                    {
                        (item['os'], item['python-version'])
                        for item in json.loads(entries['matrix'])['include']
                    },
                    expected_matrix,
                )
        self.write(panel, 'after')
        head = self.commit()
        status, entries, output = self.invoke_isolated_plan(
            '--base', base, '--head', head
        )
        self.assertEqual(status, 0, output)
        self.assertEqual(entries['mode'], 'fast')
        self.assertEqual(entries['modules'], 'test_gui_contract test_gui_root')
        self.assertEqual(
            json.loads(entries['matrix'])['include'],
            [{'os': 'ubuntu-latest', 'python-version': '3.11'}],
        )
        for missing in ('missing-base', 'missing-head'):
            with self.subTest(missing=missing):
                old = missing if missing == 'missing-base' else base
                new = missing if missing == 'missing-head' else head
                status, entries, output = self.invoke_isolated_plan(
                    '--base', old, '--head', new
                )
                self.assertEqual(status, 0, output)
                self.assertEqual(entries['mode'], 'full')
        self.write(core, 'after')
        shared_head = self.commit()
        status, entries, output = self.invoke_isolated_plan(
            '--base', head, '--head', shared_head
        )
        self.assertEqual(status, 0, output)
        self.assertEqual(entries['mode'], 'full')

    def test_plan_imports_only_standard_library_and_inventory(self) -> None:
        """The planner does not load runner, supervisor, SDK, or psutil.

        Args:
            None
        Returns:
            None
        """
        self.install_plan_scripts()
        code = (
            'import builtins, sys\n'
            'original = builtins.__import__\n'
            'blocked = ("scripts.run_tests", "scripts.test_supervision", '
            '"metor", "psutil")\n'
            'def guarded(name, *args, **kwargs):\n'
            '    if any(name == item or name.startswith(item + ".") '
            'for item in blocked):\n'
            '        raise AssertionError("planner loaded runtime dependency")\n'
            '    return original(name, *args, **kwargs)\n'
            'builtins.__import__ = guarded\n'
            'import scripts.test_inventory, scripts.ci_impact\n'
            'assert not any(name == item or name.startswith(item + ".") '
            'for name in sys.modules for item in blocked)\n'
        )
        environment = os.environ.copy()
        environment.pop('PYTHONPATH', None)
        environment['PYTHONDONTWRITEBYTECODE'] = '1'
        result = subprocess.run(
            [sys.executable, '-S', '-c', code],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unclassified_file_still_invalidates_runner_inventory(self) -> None:
        """The shared inventory retains the runner's complete-file gate.

        Args:
            None
        Returns:
            None
        """
        from scripts import run_tests
        from scripts.test_inventory import FAST_MODULES, INTEGRATION_MODULES

        self.assertIs(run_tests.FAST_MODULES, FAST_MODULES)
        self.assertIs(run_tests.INTEGRATION_MODULES, INTEGRATION_MODULES)
        self.assertIs(ci_impact.INTEGRATION_MODULES, INTEGRATION_MODULES)
        tests = self.root / 'tests'
        tests.mkdir()
        for module in FAST_MODULES + INTEGRATION_MODULES:
            (tests / f'{module}.py').touch()
        with patch.object(run_tests, 'TESTS', tests):
            self.assertIsNone(run_tests.validate_manifest())
            (tests / 'test_new_unclassified.py').touch()
            self.assertIn(
                '1 unclassified files, 0 missing files',
                run_tests.validate_manifest() or '',
            )

    def test_existing_gui_renderer_modification_selects_known_modules(self) -> None:
        """A content edit to the sole known renderer retains a narrow check.

        Args:
            None
        Returns:
            None
        """
        name = 'src/metor/ui/gui/views/root/panel.py'
        self.write(name, 'before')
        base = self.commit()
        self.write(name, 'after')
        head = self.commit()
        self.assertEqual(ci_impact.changed_regular_paths(base, head, self.root), [name])
        self.assertEqual(
            self.classify(base, head),
            ('fast', ('test_gui_contract', 'test_gui_root')),
        )

    def test_shared_packaging_and_workflow_changes_require_full(self) -> None:
        """Known cross-cutting areas cannot inherit the GUI-only mapping.

        Args:
            None
        Returns:
            None
        """
        names = (
            'src/metor/client/frontends.py',
            'src/metor/core/tor.py',
            'src/metor/data/profile/catalog.py',
            'requirements/dev.txt',
            'packaging/sdk/pyproject.toml',
            '.github/workflows/ci.yml',
        )
        for name in names:
            self.write(name, 'before')
        base = self.commit()
        for name in names:
            with self.subTest(name=name):
                self.write(name, 'after')
                head = self.commit()
                self.assertEqual(self.classify(base, head), ('full', ()))
                base = head

    def test_renames_include_both_sides_under_any_git_setting(self) -> None:
        """A move between Core and an allowed GUI path always needs full CI.

        Args:
            None
        Returns:
            None
        """
        core = self.root / 'src/metor/core/old_runtime.py'
        gui = self.root / 'src/metor/ui/gui/theme.py'
        self.write('src/metor/core/old_runtime.py', 'same bytes')
        base = self.commit()
        gui.parent.mkdir(parents=True, exist_ok=True)
        core.rename(gui)
        head = self.commit()
        for setting in ('true', 'false'):
            with self.subTest(direction='core-to-gui', setting=setting):
                self.git('config', 'diff.renames', setting)
                self.assertIsNone(
                    ci_impact.changed_regular_paths(base, head, self.root)
                )
                self.assertEqual(self.classify(base, head), ('full', ()))
        base = head
        core.parent.mkdir(parents=True, exist_ok=True)
        gui.rename(core)
        head = self.commit()
        for setting in ('true', 'false'):
            with self.subTest(direction='gui-to-core', setting=setting):
                self.git('config', 'diff.renames', setting)
                self.assertEqual(self.classify(base, head), ('full', ()))

    def test_deletion_and_git_type_change_require_full(self) -> None:
        """Removed paths and symlink tree entries cannot be fast edits.

        Args:
            None
        Returns:
            None
        """
        name = 'src/metor/ui/gui/theme.py'
        self.write(name, 'regular file')
        base = self.commit()
        (self.root / name).unlink()
        head = self.commit()
        self.assertEqual(self.classify(base, head), ('full', ()))
        self.write(name, 'regular file')
        base = self.commit()
        target_blob = self.git('hash-object', '-w', '--stdin', input_bytes=b'target')
        self.git('update-index', '--cacheinfo', f'120000,{target_blob},{name}')
        self.git('commit', '-qm', 'fixture type change')
        head = self.git('rev-parse', 'HEAD')
        self.assertEqual(self.classify(base, head), ('full', ()))

    def test_unusual_file_names_remain_intact_and_conservative(self) -> None:
        """NUL parsing preserves whitespace and newlines in a Git path.

        Args:
            None
        Returns:
            None
        """
        for name in ('docs/space name.md', 'docs/line\nbreak.md'):
            with self.subTest(name=name):
                self.write(name, 'before')
                base = self.commit()
                self.write(name, 'after')
                head = self.commit()
                for quote_path in ('true', 'false'):
                    self.git('config', 'core.quotePath', quote_path)
                    self.assertEqual(
                        ci_impact.changed_regular_paths(base, head, self.root), [name]
                    )
                    self.assertEqual(self.classify(base, head), ('full', ()))

    def test_missing_or_unproven_commit_diff_requires_full(self) -> None:
        """Invalid references, stale head and empty diffs never imply fast.

        Args:
            None
        Returns:
            None
        """
        self.write('docs/GLOSSARY.md', 'before')
        base = self.commit()
        self.write('docs/GLOSSARY.md', 'after')
        head = self.commit()
        for old, new in (
            ('missing-base', head),
            (base, 'missing-head'),
            (base, base),
            (head, head),
        ):
            with self.subTest(base=old, head=new):
                self.assertIsNone(ci_impact.changed_regular_paths(old, new, self.root))
                self.assertEqual(self.classify(old, new), ('full', ()))

    def test_malformed_diff_and_unknown_status_require_full(self) -> None:
        """Partial NUL records and unknown status bytes cannot form a fast plan.

        Args:
            None
        Returns:
            None
        """
        name = b'src/metor/ui/gui/theme.py'
        for output in (
            b'M\0' + name,
            b'M\0' + name + b'\0M\0',
            b'Q\0' + name + b'\0',
            b'M\0' + name + b'\0M\0' + name + b'\0',
        ):
            with self.subTest(output=output):
                self.assertIsNone(ci_impact._parse_diff_records(output))

    def test_noninventory_mapping_requires_full(self) -> None:
        """A stale module mapping cannot produce an invalid partial plan.

        Args:
            None
        Returns:
            None
        """
        name = 'src/metor/ui/gui/theme.py'
        self.write(name, 'content')
        with patch.dict(ci_impact.ISOLATED_GUI_MODULES, {name: ('not-in-manifest',)}):
            self.assertEqual(ci_impact.decide([name], self.root), ('full', ()))

    def test_plan_output_falls_back_to_complete_matrix(self) -> None:
        """The CLI writes a full matrix when the diff basis is missing.

        Args:
            None
        Returns:
            None
        """
        self.write('docs/GLOSSARY.md', 'text')
        self.commit()
        output = self.root / 'plan.txt'
        with (
            patch.object(
                ci_impact, '__file__', str(self.root / 'scripts/ci_impact.py')
            ),
            patch.object(
                sys,
                'argv',
                [
                    'ci_impact',
                    '--base',
                    'missing-base',
                    '--head',
                    'HEAD',
                    '--github-output',
                    str(output),
                ],
            ),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(ci_impact.main(), 0)
        entries = dict(
            line.split('=', 1)
            for line in output.read_text(encoding='utf-8').splitlines()
        )
        self.assertEqual(entries['mode'], 'full')
        self.assertEqual(entries['modules'], '')
        self.assertEqual(len(json.loads(entries['matrix'])['include']), 4)

    def test_plan_output_selects_only_verified_fast_modules(self) -> None:
        """A valid isolated diff writes exactly one lane and known module IDs.

        Args:
            None
        Returns:
            None
        """
        name = 'src/metor/ui/gui/views/root/panel.py'
        self.write(name, 'before')
        base = self.commit()
        self.write(name, 'after')
        head = self.commit()
        output = self.root / 'fast-plan.txt'
        with (
            patch.object(
                ci_impact, '__file__', str(self.root / 'scripts/ci_impact.py')
            ),
            patch.object(
                sys,
                'argv',
                [
                    'ci_impact',
                    '--base',
                    base,
                    '--head',
                    head,
                    '--github-output',
                    str(output),
                ],
            ),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(ci_impact.main(), 0)
        entries = dict(
            line.split('=', 1)
            for line in output.read_text(encoding='utf-8').splitlines()
        )
        self.assertEqual(entries['mode'], 'fast')
        self.assertEqual(entries['modules'], 'test_gui_contract test_gui_root')
        self.assertEqual(
            json.loads(entries['matrix'])['include'],
            [{'os': 'ubuntu-latest', 'python-version': '3.11'}],
        )


if __name__ == '__main__':
    unittest.main()
