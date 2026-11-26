"""Record native files and database provider versions in a verified release wheelhouse."""

import hashlib
import importlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import cast
from zipfile import ZipExtFile, ZipFile


def _database_versions() -> dict[str, str]:
    """Query the extracted, hash-checked SQLCipher wheel with an ephemeral database."""
    db = importlib.import_module('sqlcipher3.dbapi2')
    conn = db.connect(':memory:')
    try:
        conn.execute("PRAGMA key = 'release-inventory'")
        conn.execute('CREATE TABLE inventory (id INTEGER)')
        components = {'sqlite': conn.execute('SELECT sqlite_version()').fetchone()[0]}
        for key in ('cipher_version', 'cipher_provider', 'cipher_provider_version'):
            value = conn.execute(f'PRAGMA {key}').fetchone()
            if not value or not isinstance(value[0], str) or not value[0]:
                raise ValueError(f'Missing runtime database component {key}')
            components[key] = value[0]
        return components
    finally:
        conn.close()


def inventory(wheelhouse: Path) -> str:
    """Inventory native binaries by wheel and include versions from the selected driver."""
    files: dict[str, dict[str, str]] = {}
    runtime: dict[str, str] = {}
    for wheel in sorted(wheelhouse.glob('*.whl')):
        with ZipFile(wheel) as archive:
            for member in archive.namelist():
                if re.search(r'(?:\.(?:dll|pyd|dylib)|\.so(?:\.\d+)*)$', member, re.I):
                    with archive.open(member) as content:
                        files.setdefault(wheel.name, {})[member] = hashlib.file_digest(
                            cast(ZipExtFile, content), 'sha256'
                        ).hexdigest()
            if wheel.name.startswith(('sqlcipher3-', 'sqlcipher3_binary-')):
                with tempfile.TemporaryDirectory() as directory:
                    archive.extractall(directory)
                    result = subprocess.check_output(
                        [sys.executable, '-I', '-S', __file__, directory],
                        text=True,
                    )
                    runtime = cast(dict[str, str], json.loads(result))
    return (
        json.dumps(
            {'database': runtime, 'native_files': files}, indent=2, sort_keys=True
        )
        + '\n'
    )


if __name__ == '__main__':
    sys.path.insert(0, sys.argv[1])
    print(json.dumps(_database_versions()))
