"""Check every public release and development pin on both platforms against OSV."""

import json
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from scripts.release.bundle import PIP_VERSION
from scripts.release.paths import PROJECT_ROOT


Pin = tuple[str, str, str]
PIN_PATTERN = re.compile(r'([A-Za-z0-9_.-]+)==([^\s;]+)(?:\s*;.*)?')
OSV_BATCH = 'https://api.osv.dev/v1/querybatch'


def public_pins(root: Path) -> list[Pin]:
    """Read exact PyPI and npm versions; include conditional pins regardless of this host."""
    pins = {('PyPI', 'pip', PIP_VERSION)}
    for lock in sorted((root / 'requirements').glob('*.lock')):
        for raw in lock.read_text(encoding='utf-8').splitlines():
            line = raw.partition('#')[0].strip()
            if not line or line.startswith('-r '):
                continue
            match = PIN_PATTERN.fullmatch(line)
            if not match:
                raise ValueError(f'Expected an exact package pin in {lock.name}.')
            pins.add(('PyPI', match[1], match[2]))
    npm = json.loads((root / 'package-lock.json').read_text(encoding='utf-8'))
    for path, metadata in npm['packages'].items():
        if path:
            name = metadata.get('name') or path.rsplit('node_modules/', maxsplit=1)[-1]
            pins.add(('npm', name, metadata['version']))
    return sorted(pins)


def query_osv(pins: list[Pin]) -> object:
    """Send public names and versions only. Retry transient failures; never treat them as clean."""
    queries = [
        {'version': version, 'package': {'ecosystem': ecosystem, 'name': name}}
        for ecosystem, name, version in pins
    ]
    request = Request(
        OSV_BATCH,
        data=json.dumps({'queries': queries}).encode(),
        headers={
            'Content-Type': 'application/json',
            'User-Agent': 'Metor-dependency-check',
        },
    )
    for attempt in range(3):
        try:
            with urlopen(request, timeout=20) as response:
                return json.load(response)
        except (URLError, TimeoutError) as exc:
            if attempt == 2 or (
                isinstance(exc, HTTPError) and exc.code < 500 and exc.code != 429
            ):
                raise
            time.sleep(2**attempt)
    raise RuntimeError('OSV did not return a response.')


def findings(pins: list[Pin], document: object) -> list[str]:
    """Validate the batch shape and report a known advisory against its exact package."""
    rows = document.get('results') if isinstance(document, dict) else None
    if not isinstance(rows, list) or len(rows) != len(pins):
        raise ValueError('Incomplete OSV batch response.')
    result: list[str] = []
    for pin, row in zip(pins, rows, strict=True):
        if not isinstance(row, dict) or not isinstance(row.get('vulns', []), list):
            raise ValueError('Invalid OSV package response.')
        for vuln in row.get('vulns', []):
            if not isinstance(vuln, dict) or not isinstance(vuln.get('id'), str):
                raise ValueError('Invalid OSV advisory.')
            result.append(
                f'{pin[0]} {pin[1]}=={pin[2]}: https://osv.dev/vulnerability/{vuln["id"]}'
            )
        if row.get('next_page_token') and not row.get('vulns'):
            raise ValueError('Incomplete paginated OSV response.')
    return result


def main() -> int:
    """Return failure for reported advisories, unreadable locks or an unavailable database."""
    try:
        pins = public_pins(PROJECT_ROOT)
        issues = findings(pins, query_osv(pins))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'Dependency advisory check incomplete: {exc}', file=sys.stderr)
        return 1
    print(
        f'Checked {len(pins)} pinned versions against OSV; {len(issues)} advisory matches.'
    )
    for issue in issues:
        print(issue)
    return int(bool(issues))


if __name__ == '__main__':
    raise SystemExit(main())
