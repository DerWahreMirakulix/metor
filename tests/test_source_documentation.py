"""Production source documentation contract regressions."""

import ast
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SourceDocumentationTests(unittest.TestCase):
    """Checks production modules and executable callable documentation."""

    def test_production_functions_have_complete_contract_docstrings(self) -> None:
        """Requires descriptions plus explicit input and output contracts.

        Args:
            None

        Returns:
            None
        """
        tracked = subprocess.run(
            ['git', 'ls-files', 'src/**/*.py', 'packaging/**/*.py'],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        failures: list[str] = []
        for relative in tracked:
            path = ROOT / relative
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=relative)
            if not ast.get_docstring(tree):
                failures.append(f'{relative}: missing module docstring')
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                docstring = ast.get_docstring(node) or ''
                missing = [
                    section
                    for section in ('description', 'Args:', 'Returns:')
                    if (
                        not docstring
                        if section == 'description'
                        else section not in docstring
                    )
                ]
                if missing:
                    failures.append(
                        f'{relative}:{node.lineno} {node.name}: missing '
                        + ', '.join(missing)
                    )
        self.assertEqual(failures, [], '\n' + '\n'.join(failures))


if __name__ == '__main__':
    unittest.main()
