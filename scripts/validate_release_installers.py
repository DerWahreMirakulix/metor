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
            inventory = run([str(executable), '-I', '-m', 'metor', 'chat', '--list-ui'])
            has_terminal = 'metor-ui-terminal' in inventory
            if has_terminal != archive.name.startswith('metor-ui-terminal-'):
                raise RuntimeError(
                    'Installer did not resolve its declared frontend target.'
                )
        print('NATIVE_OFFLINE_ZIP_OK', archive.name)


def main() -> None:
    """Validates all three native release variants supplied by the caller."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle_root', type=Path)
    root = parser.parse_args().bundle_root
    archives = sorted(root.glob('*.zip'))
    if len(archives) != 3:
        raise ValueError('Expected SDK, base and Terminal ZIPs.')
    for archive in archives:
        validate_zip(archive)


if __name__ == '__main__':
    main()
