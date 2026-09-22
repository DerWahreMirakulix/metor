"""Regression coverage for nonmutating local and continuous quality gates."""

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class QualityGateContractTests(unittest.TestCase):
    """Keeps the advertised check path complete and side-effect free."""

    def test_ready_alias_runs_complete_nonmutating_check_path(self) -> None:
        """Requires readiness to include architecture, freshness, and tests.

        Args:
            None

        Returns:
            None
        """
        scripts = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))[
            'scripts'
        ]

        self.assertEqual(scripts['ready'], 'npm run check')
        check = scripts['check']
        for required in (
            'check:md',
            'check:py',
            'check:types',
            'check:boundaries',
            'check:generated',
            'npm test',
        ):
            self.assertIn(required, check)
        self.assertNotIn('--fix', scripts['check:py'])
        self.assertNotIn('--write', scripts['check:md'])
        self.assertNotIn('generate:', check)

    def test_ci_covers_minimum_and_newer_python_and_explicit_fixtures(self) -> None:
        """Rejects a 3.11-only matrix and discovery-only native-fixture claims.

        Args:
            None

        Returns:
            None
        """
        workflow = (ROOT / '.github' / 'workflows' / 'ci.yml').read_text(
            encoding='utf-8'
        )

        self.assertIn('- "3.11"', workflow)
        self.assertIn('- "3.13"', workflow)
        self.assertIn('tests/gui_native_capture.py --view root_refresh', workflow)
        self.assertIn('tests/gui_native_capture.py --view setting_keyboard', workflow)
        self.assertIn('tests/gui_stream_pressure.py --result', workflow)
        for runtime_package in ('libegl1', 'libegl-mesa0', 'libgl1-mesa-dri'):
            self.assertIn(runtime_package, workflow)
        self.assertIn("ctypes.CDLL('libEGL.so.1')", workflow)
        self.assertIn('actions/upload-artifact@', workflow)
        for artifact in (
            'root-refresh.png',
            'setting-keyboard.png',
            'root-refresh.log',
            'setting-keyboard.log',
            'stream-pressure.json',
            'stream-pressure.log',
        ):
            self.assertIn(artifact, workflow)


if __name__ == '__main__':
    unittest.main()
