"""Canonical documentation ownership and internal-link regressions."""

import hashlib
import json
from pathlib import Path
import re
import unittest
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_DOCUMENTS = (
    ROOT / 'README.md',
    ROOT / 'AGENTS.md',
    ROOT / 'docs' / 'AGENTS.md',
    ROOT / 'docs' / 'ARCHITECTURE.md',
    ROOT / 'docs' / 'CONTRIBUTE.md',
    ROOT / 'docs' / 'GLOSSARY.md',
    ROOT / 'docs' / 'RELEASING.md',
    ROOT / 'docs' / 'governance' / 'AUDIT.md',
    ROOT / 'docs' / 'contracts' / 'FRONTENDS.md',
    ROOT / 'docs' / 'contracts' / 'GUI.md',
    ROOT / 'docs' / 'contracts' / 'GUI_INTEGRATION_MAP.md',
    ROOT / 'docs' / 'contracts' / 'GUI_PLATFORM_ADR.md',
)
SPEC_HASHES = {
    'METOR_GUI_SPEC.md': '8907c510aeb7cf9272816e60bd1c09a2f38c31c7d340d67859163254f2c8cca7',
    'METOR_GUI_LAYOUT_SPEC.md': '3202019b3fd3e7aef472d281006cdb35c1caf073dbaaf2ee75bf691eeaadf5b0',
}
LINK = re.compile(r'(?<!!)\[[^]]*\]\(([^)]+)\)')


def _anchors(path: Path) -> set[str]:
    """Collects predictable GitHub-style heading anchors from one document.

    Args:
        path: Markdown document to inspect.

    Returns:
        set[str]: Normalized heading anchors in the document.
    """
    anchors: set[str] = set()
    for line in path.read_text(encoding='utf-8').splitlines():
        match = re.match(r'^#{1,6}\s+(.+?)\s*#*$', line)
        if match is None:
            continue
        anchor = match.group(1).strip().lower()
        anchor = re.sub(r'[^\w\- ]', '', anchor, flags=re.UNICODE)
        anchors.add(anchor.replace(' ', '-'))
    return anchors


class DocumentationContractTests(unittest.TestCase):
    """Checks active documentation names, provenance, and navigation."""

    def test_frontend_contract_and_spec_inputs_have_one_active_owner(self) -> None:
        """Requires the neutral contract and only durable approved GUI inputs.

        Args:
            None

        Returns:
            None
        """
        self.assertTrue((ROOT / 'docs/contracts/FRONTENDS.md').is_file())
        self.assertFalse((ROOT / 'docs/contracts/EMBEDDED_UI.md').exists())
        self.assertFalse((ROOT / 'docs/.temp').exists())
        for name, expected in SPEC_HASHES.items():
            payload = (ROOT / 'docs/specs' / name).read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), expected, name)

    def test_general_markdown_formatting_excludes_specs_and_generated_refs(
        self,
    ) -> None:
        """Protects immutable inputs and generated references from broad writes.

        Args:
            None

        Returns:
            None
        """
        ignored = (ROOT / '.prettierignore').read_text(encoding='utf-8').splitlines()
        self.assertIn('docs/specs/', ignored)
        self.assertIn('docs/generated/', ignored)
        formatter = (ROOT / 'scripts/format_generated_docs.py').read_text(
            encoding='utf-8'
        )
        self.assertIn("'prettier-generated.ignore'", formatter)

    def test_gui_status_does_not_claim_acceptance_with_native_gates_open(self) -> None:
        """Keeps the machine-readable status aligned with named native gaps.

        Args:
            None

        Returns:
            None
        """
        support = json.loads(
            (ROOT / 'docs/contracts/gui/support.json').read_text(encoding='utf-8')
        )
        self.assertNotIn('gui_implementation_percent', support['completion'])
        self.assertFalse(support['acceptance_at_claimed_support_level'])
        self.assertIn('pending', support['status'])
        self.assertIn('pending', support['completion']['mandatory_native_acceptance'])

    def test_active_markdown_file_and_anchor_links_resolve(self) -> None:
        """Checks local navigation without reclassifying historical evidence.

        Args:
            None

        Returns:
            None
        """
        failures: list[str] = []
        for source in ACTIVE_DOCUMENTS:
            if not source.is_file():
                failures.append(f'{source.relative_to(ROOT)}: missing active document')
                continue
            text = source.read_text(encoding='utf-8')
            for raw in LINK.findall(text):
                destination = raw.split(maxsplit=1)[0].strip('<>')
                if destination.startswith(('http://', 'https://', 'mailto:')):
                    continue
                path_text, _, anchor = destination.partition('#')
                target = source if not path_text else source.parent / unquote(path_text)
                target = target.resolve()
                try:
                    target.relative_to(ROOT)
                except ValueError:
                    failures.append(f'{source.relative_to(ROOT)}: outside link {raw}')
                    continue
                if not target.exists():
                    failures.append(f'{source.relative_to(ROOT)}: missing {raw}')
                    continue
                if anchor and target.suffix.lower() == '.md':
                    normalized = unquote(anchor).lower()
                    if normalized not in _anchors(target):
                        failures.append(
                            f'{source.relative_to(ROOT)}: missing anchor {raw}'
                        )
        self.assertEqual(failures, [], '\n' + '\n'.join(failures))


if __name__ == '__main__':
    unittest.main()
