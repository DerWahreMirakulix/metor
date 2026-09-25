"""Exercise conservative CI impact decisions against actual Git commits."""

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
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
