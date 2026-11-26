"""Canonical repository paths for generated release documentation."""

from pathlib import Path


PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
GENERATED_DOCS_DIR: Path = PROJECT_ROOT / 'docs' / 'generated'
API_DOC_PATH: Path = GENERATED_DOCS_DIR / 'API.md'
SETTINGS_DOC_PATH: Path = GENERATED_DOCS_DIR / 'SETTINGS.md'
API_SCHEMA_PATH: Path = GENERATED_DOCS_DIR / 'api.schema.json'
COMPATIBILITY_MANIFEST_PATH: Path = GENERATED_DOCS_DIR / 'compatibility.json'
