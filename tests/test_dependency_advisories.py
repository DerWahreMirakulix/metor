"""Regression coverage for the complete cross-platform dependency advisory gate."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.check_dependency_advisories import findings, public_pins


class DependencyAdvisoryTests(unittest.TestCase):
    """Security checks must not lose a platform or silently accept partial data."""

    def test_host_markers_and_scoped_npm_dependencies_are_checked(self) -> None:
        """Both native pins and the scoped package reach the same query on any host."""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            deps = root / 'requirements'
            deps.mkdir()
            (deps / 'runtime.lock').write_text(
                'posix-wheel==1.0 ; platform_system == "Linux"\n'
                'win-wheel==2.0 ; platform_system == "Windows"\n',
                encoding='utf-8',
            )
            (root / 'package-lock.json').write_text(
                '{"packages":{"":{},"node_modules/@example/project":{"version":"1.2.0"}}}',
                encoding='utf-8',
            )
            pins = public_pins(root)
            self.assertIn(('PyPI', 'posix-wheel', '1.0'), pins)
            self.assertIn(('PyPI', 'win-wheel', '2.0'), pins)
            self.assertIn(('npm', '@example/project', '1.2.0'), pins)

    def test_empty_success_and_incomplete_batch_are_distinct(self) -> None:
        """A missing result cannot turn a known or unknown package into a clean one."""
        pins = [('PyPI', 'example', '1.0')]
        self.assertEqual(findings(pins, {'results': [{}]}), [])
        self.assertEqual(
            findings(pins, {'results': [{'vulns': [{'id': 'TEST-1'}]}]}),
            ['PyPI example==1.0: https://osv.dev/vulnerability/TEST-1'],
        )
        with self.assertRaises(ValueError):
            findings(pins, {'results': []})
