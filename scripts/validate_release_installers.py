"""Executes each native offline ZIP installer in a fresh disposable extraction."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from zipfile import ZipFile


def validate_zip(archive: Path) -> None:
    """Extracts a built archive and verifies its explicit offline install target."""
    with tempfile.TemporaryDirectory(prefix='metor-offline-') as directory:
        root = Path(directory)
        with ZipFile(archive) as bundle:
            for member in bundle.namelist():
                if Path(member).is_absolute() or '..' in Path(member).parts:
                    raise ValueError('Unsafe release archive member.')
            bundle.extractall(root)
        installer_name = 'install.cmd' if os.name == 'nt' else 'install.sh'
        installers = tuple(root.rglob(installer_name))
        if len(installers) != 1:
            raise ValueError('Release must have exactly one installer.')
        installer = installers[0]
        subprocess.run(
            [
                sys.executable,
                str(installer.parent / 'verify_bundle.py'),
                str(installer.parent),
            ],
            cwd=installer.parent,
            check=True,
        )
        environment = {
            k: v for k, v in os.environ.items() if k not in {'PYTHONPATH', 'MYPYPATH'}
        }
        environment['PATH'] = (
            str(Path(sys.executable).parent) + os.pathsep + environment.get('PATH', '')
        )

        def run(args: list[str]) -> str:
            result = subprocess.run(
                args,
                cwd=installer.parent,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=180,
            )
            print(result.stdout, end='')
            if result.returncode:
                raise RuntimeError(
                    f'Offline installer/probe failed: {archive.name}, exit {result.returncode}'
                )
            return result.stdout

        run(
            ['cmd.exe', '/d', '/c', str(installer)]
            if os.name == 'nt'
            else ['sh', str(installer)]
        )
        executable = (
            installer.parent
            / '.venv'
            / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        )
        run([str(executable), '-m', 'pip', 'check'])
        run(
            [
                str(executable),
                '-I',
                '-c',
                'import sys, metor.client; print(sys.version); print(metor.client.__file__)',
            ]
        )
        if not archive.name.startswith('metor-sdk-'):
            run([str(executable), '-I', '-m', 'metor', '--version'])
            inventory = run(
                [str(executable), '-I', '-m', 'metor', 'chat', '--list-uis']
            )
            has_terminal = 'metor-ui-terminal' in inventory
            if has_terminal != archive.name.startswith('metor-ui-terminal-'):
                raise RuntimeError(
                    'Installer did not resolve its declared frontend target.'
                )
            has_gui = 'metor-ui-gui' in inventory
            if has_gui != archive.name.startswith('metor-ui-gui-'):
                raise RuntimeError('Installer did not resolve its declared GUI target.')
            if has_gui:
                run(
                    [
                        str(executable),
                        '-I',
                        '-c',
                        'import sys; from metor.client import load_frontend; '
                        'assert load_frontend("gui"); assert "kivy" not in sys.modules',
                    ]
                )
                run(
                    [
                        str(executable),
                        '-I',
                        '-m',
                        'metor',
                        'chat',
                        '--ui',
                        'gui',
                        '--help',
                    ]
                )
        print('NATIVE_OFFLINE_ZIP_OK', archive.name)


def main() -> None:
    """Validates all four native release variants supplied by the caller."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle_root', type=Path)
    root = parser.parse_args().bundle_root
    archives = sorted(root.glob('*.zip'))
    if len(archives) != 4:
        raise ValueError('Expected SDK, base, Terminal and GUI ZIPs.')
    prefixes = {
        'base': 'metor-wheelhouse-',
        'gui': 'metor-ui-gui-wheelhouse-',
        'sdk': 'metor-sdk-wheelhouse-',
        'terminal': 'metor-ui-terminal-wheelhouse-',
    }
    identities = {
        variant
        for archive in archives
        for variant, prefix in prefixes.items()
        if archive.name.startswith(prefix)
    }
    if identities != set(prefixes):
        raise ValueError('Release ZIP identities must be SDK, base, Terminal and GUI.')
    for archive in archives:
        validate_zip(archive)


if __name__ == '__main__':
    main()
