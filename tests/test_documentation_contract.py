"""Canonical documentation ownership, status, and local-link regressions."""

from pathlib import Path
import re
import tempfile
import unittest
from urllib.parse import unquote

from metor.ui.gui.platform import DeviceConfigurationError, read_configuration


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_DOCUMENTS = (
    ROOT / 'README.md',
    ROOT / 'AGENTS.md',
    ROOT / 'docs' / 'AGENTS.md',
    ROOT / 'docs' / 'ARCHITECTURE.md',
    ROOT / 'docs' / 'CONTRIBUTE.md',
    ROOT / 'docs' / 'GLOSSARY.md',
    ROOT / 'docs' / 'RELEASING.md',
    ROOT / 'docs' / 'contracts' / 'GUI.md',
    ROOT / 'docs' / 'contracts' / 'FRONTENDS.md',
)
RETIRED_DIRECTORIES = (
    ROOT / 'docs' / 'audits',
    ROOT / 'docs' / 'gui',
    ROOT / 'docs' / 'reference',
    ROOT / 'docs' / 'governance',
    ROOT / 'docs' / 'specs',
)
RETIRED_REFERENCES = (
    'docs/audits/',
    'docs/gui/',
    'docs/reference/',
    'docs/governance/',
    'docs/specs/',
    'GUI_INTEGRATION_MAP.md',
    'GUI_PLATFORM_ADR.md',
    'FINAL_CLOSURE_WORKLOG.md',
    'GUI_IMPLEMENTATION_2026-09-12.md',
)
LINK = re.compile(r'(?<!!)\[[^]]*\]\(([^)]+)\)')


def _anchors(path: Path) -> set[str]:
    """Collect predictable GitHub-style heading anchors from one document.

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
    """Check maintained ownership, traceability, status, and navigation."""

    def test_target_ownership_tree_is_complete(self) -> None:
        """Require the maintained owners and reject superseded hierarchies.

        Args:
            None.

        Returns:
            None.
        """
        for path in ACTIVE_DOCUMENTS:
            self.assertTrue(path.is_file(), path.relative_to(ROOT))
        self.assertFalse((ROOT / 'docs/README.md').exists())
        for path in RETIRED_DIRECTORIES:
            self.assertFalse(path.exists(), path.relative_to(ROOT))

    def test_gui_contract_keeps_durable_behavior_and_design(self) -> None:
        """Protect the consolidated product and visual contract sections.

        Args:
            None.

        Returns:
            None.
        """
        gui = (ROOT / 'docs/contracts/GUI.md').read_text(encoding='utf-8')
        for section in (
            '## Device configuration (`device.toml`)',
            '## Navigation and communication',
            '## Voice and media',
            '## Privacy and lifecycle',
            '## Design and accessibility',
        ):
            self.assertIn(section, gui)
        self.assertIn('360 × 640 logical units', gui)
        self.assertIn('PlatformBindings', gui)

    def test_canonical_gui_contract_has_no_historical_checkpoint(self) -> None:
        """Keep historical input hashes in Git history instead of product docs.

        Args:
            None.

        Returns:
            None.
        """
        gui = (ROOT / 'docs/contracts/GUI.md').read_text(encoding='utf-8')
        self.assertNotRegex(gui, r'[a-f0-9]{40}')
        self.assertNotRegex(gui, r'[a-f0-9]{64}')

    def test_general_markdown_formatting_excludes_only_generated_refs(self) -> None:
        """Keep generated references outside broad Markdown rewrites.

        Args:
            None.

        Returns:
            None.
        """
        ignored = (ROOT / '.prettierignore').read_text(encoding='utf-8').splitlines()
        self.assertIn('docs/generated/', ignored)
        self.assertNotIn('docs/specs/', ignored)
        formatter = (ROOT / 'scripts/format_generated_docs.py').read_text(
            encoding='utf-8'
        )
        self.assertIn("'prettier-generated.ignore'", formatter)
        attributes = (ROOT / '.gitattributes').read_text(encoding='utf-8')
        self.assertNotIn('/docs/specs/', attributes)

    def test_gui_capability_claims_are_bounded(self) -> None:
        """Keep physical and acoustic claims tied to actual adapters and evidence.

        Args:
            None.

        Returns:
            None.
        """
        gui = (ROOT / 'docs/contracts/GUI.md').read_text(encoding='utf-8')
        self.assertIn('no registered production physical appliance adapter', gui)
        self.assertIn('speaker echo cancellation', gui)
        self.assertIn('simulator', gui)

    def test_physical_configuration_requires_injected_bindings(self) -> None:
        """Ensure a simulator description cannot activate a physical device.

        Args:
            None.

        Returns:
            None.
        """
        example = ROOT / 'docs/examples/gui-simulator.toml'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'device.toml'
            path.write_bytes(example.read_bytes())
            with self.assertRaises(DeviceConfigurationError):
                read_configuration(str(path), simulator=False)

    def test_simulator_example_parses_with_production_validator(self) -> None:
        """Validate the maintained TOML example through the real GUI parser.

        Args:
            None.

        Returns:
            None.
        """
        example = ROOT / 'docs/examples/gui-simulator.toml'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'device.toml'
            path.write_bytes(example.read_bytes())
            configuration = read_configuration(str(path), simulator=True)
        self.assertEqual(configuration.mode, 'simulator')
        self.assertEqual(configuration.logical_size, (480, 800))

    def test_readme_uses_the_canonical_cli_grammar(self) -> None:
        """Prevent abbreviated or misplaced options in operator examples.

        Args:
            None.

        Returns:
            None.
        """
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertNotRegex(readme, r'--list-ui(?!s)')
        self.assertNotIn('--locked daemon', readme)
        self.assertIn('metor -p my_server daemon --locked', readme)

    def test_active_documents_do_not_reference_retired_paths(self) -> None:
        """Reject obsolete authority, worklog, and contract path references.

        Args:
            None.

        Returns:
            None.
        """
        for source in ACTIVE_DOCUMENTS:
            text = source.read_text(encoding='utf-8')
            for retired in RETIRED_REFERENCES:
                self.assertNotIn(retired, text, source.relative_to(ROOT))

    def test_active_markdown_file_and_anchor_links_resolve(self) -> None:
        """Check local navigation among all maintained authored documents.

        Args:
            None.

        Returns:
            None.
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
