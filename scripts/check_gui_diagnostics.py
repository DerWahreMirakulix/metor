"""Check the zero-baseline GUI files with the pinned editor diagnostics."""

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUI_FILES = (
    'src/metor/ui/gui/app.py',
    'src/metor/ui/gui/platform/configuration.py',
    'src/metor/ui/gui/runtime/controller.py',
    'src/metor/ui/gui/views/contacts/panel.py',
    'src/metor/ui/gui/widgets/controls.py',
    'tests/gui_native_capture.py',
)


def _supports_gui_checks(python: Path) -> bool:
    """Check that an interpreter can resolve the GUI and Ruff dependencies."""
    if not python.is_file():
        return False
    try:
        probe = subprocess.run(
            [
                str(python),
                '-c',
                'from importlib.util import find_spec; '
                'raise SystemExit(0 if find_spec("ruff") and find_spec("kivy") else 1)',
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    return probe.returncode == 0


def _gui_python() -> Path | None:
    """Prefer the checkout environment, then a configured CI interpreter."""
    candidates = (
        ROOT / '.venv' / 'python.exe',
        ROOT / '.venv' / 'Scripts' / 'python.exe',
        ROOT / '.venv' / 'bin' / 'python',
        Path(sys.executable),
    )
    return next((python for python in candidates if _supports_gui_checks(python)), None)


def main() -> int:
    """Run focused Ruff and Basedpyright checks with a GUI-ready Python.

    Returns:
        Zero only if both diagnostic engines report no issues.
    """
    node = shutil.which('node')
    basedpyright = ROOT / 'node_modules' / 'basedpyright' / 'index.js'
    if node is None or not basedpyright.is_file():
        print(
            'Install Node.js and run npm ci before checking GUI diagnostics.',
            file=sys.stderr,
        )
        return 1

    python = _gui_python()
    if python is None:
        print(
            'No Python with Ruff and Kivy is available. Install the checkout '
            'dependencies in .venv or activate a configured development environment.',
            file=sys.stderr,
        )
        return 1

    ruff = subprocess.run(
        [
            str(python),
            '-m',
            'ruff',
            'check',
            '--select',
            'I,BLE001,SIM114,RUF100',
            *GUI_FILES,
        ],
        cwd=ROOT,
        check=False,
    )
    passed = ruff.returncode == 0
    for platform in ('Linux', 'Windows'):
        for version in ('3.11', '3.13'):
            print(f'Basedpyright {platform} / Python {version}', flush=True)
            pyright = subprocess.run(
                [
                    node,
                    str(basedpyright),
                    '--warnings',
                    '--pythonpath',
                    str(python),
                    '--pythonplatform',
                    platform,
                    '--pythonversion',
                    version,
                    *GUI_FILES,
                ],
                cwd=ROOT,
                check=False,
            )
            passed = pyright.returncode == 0 and passed
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
