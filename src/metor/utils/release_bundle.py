"""Helpers for building platform-specific Metor release wheel bundles."""

import argparse
import hashlib
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from textwrap import dedent
from typing import Iterable, Sequence


PIP_VERSION: str = '26.0.1'
DEFAULT_OUTPUT_DIR: Path = Path('dist') / 'release'
WHEELHOUSE_DIRNAME: str = 'wheelhouse'
INSTALL_GUIDE_NAME: str = 'INSTALL.txt'
INSTALL_SHELL_NAME: str = 'install.sh'
INSTALL_WINDOWS_NAME: str = 'install.cmd'
CHECKSUM_FILE_NAME: str = 'SHA256SUMS.txt'


def normalize_machine(machine: str) -> str:
    """
    Normalizes a host machine identifier into a stable artifact label.

    Args:
        machine (str): The raw platform machine string.

    Returns:
        str: The normalized machine identifier.
    """
    normalized: str = machine.strip().lower()
    aliases: dict[str, str] = {
        'amd64': 'x86_64',
        'x64': 'x86_64',
        'x86-64': 'x86_64',
        'aarch64': 'arm64',
    }
    if not normalized:
        return 'unknown'
    return aliases.get(normalized, normalized)


def build_bundle_name(
    system_name: str,
    machine: str,
    python_major: int,
    python_minor: int,
) -> str:
    """
    Builds the release bundle folder name for one platform and Python version.

    Args:
        system_name (str): The host operating system name.
        machine (str): The host architecture label.
        python_major (int): The Python major version.
        python_minor (int): The Python minor version.

    Returns:
        str: The bundle directory name.
    """
    system_slug: str = system_name.strip().lower() or 'unknown'
    machine_slug: str = normalize_machine(machine)
    return (
        f'metor-wheelhouse-{system_slug}-{machine_slug}-py{python_major}{python_minor}'
    )


def build_install_guide(bundle_name: str) -> str:
    """
    Builds the human-readable offline installation guide for one bundle.

    Args:
        bundle_name (str): The generated bundle directory name.

    Returns:
        str: The installation guide text.
    """
    return dedent(
        f"""\
        Metor release bundle: {bundle_name}

        This archive contains the Metor wheel plus all Python runtime wheels
        required for this host platform. Install Tor separately from the
        official Tor Project sources.

        Simplest installation:

          Linux:   sh {INSTALL_SHELL_NAME}
          Windows: {INSTALL_WINDOWS_NAME}

        Both scripts create a local .venv inside the extracted bundle and
        install Metor entirely from the bundled wheelhouse.

        Manual fallback:

          python -m venv .venv
                    .venv/bin/python -m pip install --no-index --find-links wheelhouse --upgrade pip=={PIP_VERSION}
          .venv/bin/python -m pip install --no-index --find-links wheelhouse metor

        On Windows PowerShell, use:

                    .venv\\Scripts\\python.exe -m pip install --no-index --find-links wheelhouse --upgrade pip=={PIP_VERSION}
          .venv\\Scripts\\python.exe -m pip install --no-index --find-links wheelhouse metor

                The --no-index flag ensures installation stays inside this bundle,
                requires no package index access, and never falls back to building
                native extensions on the target host.
        """
    )


def build_install_shell_script() -> str:
    """
    Builds the Linux shell installer shipped inside one release bundle.

    Args:
        None

    Returns:
        str: The shell installer script.
    """
    return dedent(
        f"""\
        #!/usr/bin/env sh
        set -eu

        script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
        venv_dir="$script_dir/.venv"
        python_bin=''

        for candidate in python3 python; do
          if command -v "$candidate" >/dev/null 2>&1; then
            python_bin="$candidate"
            break
          fi
        done

        if [ -z "$python_bin" ]; then
          echo 'Python 3.11 or newer is required.' >&2
          exit 1
        fi

                if ! "$python_bin" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"; then
                    echo 'Python 3.11 or newer is required.' >&2
                    exit 1
                fi

        "$python_bin" -m venv "$venv_dir"
                "$venv_dir/bin/python" -m pip install --no-index --find-links "$script_dir/{WHEELHOUSE_DIRNAME}" --upgrade pip=={PIP_VERSION}
        "$venv_dir/bin/python" -m pip install --no-index --find-links "$script_dir/{WHEELHOUSE_DIRNAME}" metor

        echo "Metor installed in $venv_dir"
        echo "Run $venv_dir/bin/metor --help to verify the install."
        """
    )


def build_install_windows_script() -> str:
    """
    Builds the Windows batch installer shipped inside one release bundle.

    Args:
        None

    Returns:
        str: The Windows batch installer script.
    """
    return dedent(
        f"""\
        @echo off
        setlocal
        set "SCRIPT_DIR=%~dp0"
        set "VENV_DIR=%SCRIPT_DIR%.venv"
                set "VERSION_CHECK=import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"

        if exist "%VENV_DIR%\\Scripts\\python.exe" goto install

        where py >nul 2>nul
        if %ERRORLEVEL%==0 (
                    py -3.11 -c "%VERSION_CHECK%" >nul 2>nul
                    if %ERRORLEVEL%==0 (
                        py -3.11 -m venv "%VENV_DIR%" >nul 2>nul
                        if exist "%VENV_DIR%\\Scripts\\python.exe" goto install
                        rd /s /q "%VENV_DIR%" >nul 2>nul
                    )
                    py -3 -c "%VERSION_CHECK%" >nul 2>nul
                    if %ERRORLEVEL%==0 (
                        py -3 -m venv "%VENV_DIR%" >nul 2>nul
                        if exist "%VENV_DIR%\\Scripts\\python.exe" goto install
                        rd /s /q "%VENV_DIR%" >nul 2>nul
                    )
        )

        where python >nul 2>nul
        if %ERRORLEVEL%==0 (
                    python -c "%VERSION_CHECK%" >nul 2>nul
                    if not %ERRORLEVEL%==0 goto wrong_python
          python -m venv "%VENV_DIR%"
          goto install
        )

                :wrong_python
        echo Python 3.11 or newer is required.
        exit /b 1

        :install
                "%VENV_DIR%\\Scripts\\python.exe" -c "%VERSION_CHECK%" >nul 2>nul || goto wrong_python
                "%VENV_DIR%\\Scripts\\python.exe" -m pip install --no-index --find-links "%SCRIPT_DIR%{WHEELHOUSE_DIRNAME}" --upgrade pip=={PIP_VERSION} || exit /b 1
        "%VENV_DIR%\\Scripts\\python.exe" -m pip install --no-index --find-links "%SCRIPT_DIR%{WHEELHOUSE_DIRNAME}" metor || exit /b 1
        echo Metor installed in "%VENV_DIR%"
        echo Run "%VENV_DIR%\\Scripts\\metor.exe --help" to verify the install.
        endlocal
        """
    )


def run_command(command: Sequence[str], cwd: Path) -> None:
    """
    Executes one subprocess command and fails fast on non-zero exit codes.

    Args:
        command (Sequence[str]): The command line to execute.
        cwd (Path): The working directory for the command.

    Raises:
        subprocess.CalledProcessError: If the command exits with a non-zero code.

    Returns:
        None
    """
    subprocess.run(command, cwd=str(cwd), check=True)


def write_text_file(file_path: Path, content: str) -> None:
    """
    Writes one UTF-8 text file, creating parent directories as needed.

    Args:
        file_path (Path): The target file path.
        content (str): The text content to write.

    Returns:
        None
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding='utf-8')


def write_executable_text_file(file_path: Path, content: str) -> None:
    """
    Writes one text file and marks it executable for Unix-like hosts.

    Args:
        file_path (Path): The target file path.
        content (str): The text content to write.

    Returns:
        None
    """
    write_text_file(file_path, content)
    file_path.chmod(0o755)


def iter_bundle_files(bundle_dir: Path) -> Iterable[Path]:
    """
    Iterates all files inside one bundle directory except the checksum manifest.

    Args:
        bundle_dir (Path): The bundle directory to scan.

    Returns:
        Iterable[Path]: The files that should appear in the checksum manifest.
    """
    for file_path in sorted(path for path in bundle_dir.rglob('*') if path.is_file()):
        if file_path.name == CHECKSUM_FILE_NAME:
            continue
        yield file_path


def build_sha256_manifest(bundle_dir: Path) -> str:
    """
    Builds the SHA256 checksum manifest for one release bundle.

    Args:
        bundle_dir (Path): The bundle directory to hash.

    Returns:
        str: The checksum manifest contents.
    """
    lines: list[str] = []
    for file_path in iter_bundle_files(bundle_dir):
        digest: str = hashlib.sha256(file_path.read_bytes()).hexdigest()
        relative_path: str = file_path.relative_to(bundle_dir).as_posix()
        lines.append(f'{digest}  {relative_path}')
    return '\n'.join(lines) + '\n'


def archive_bundle(bundle_dir: Path) -> Path:
    """
    Archives one release bundle directory into a zip file beside the folder.

    Args:
        bundle_dir (Path): The bundle directory to archive.

    Returns:
        Path: The generated zip archive path.
    """
    archive_base: str = str(bundle_dir)
    return Path(
        shutil.make_archive(
            archive_base,
            'zip',
            bundle_dir.parent,
            bundle_dir.name,
        )
    )


def build_release_wheelhouse(
    output_dir: Path,
    skip_pip_upgrade: bool = False,
) -> Path:
    """
    Builds the platform-specific runtime wheel bundle in the target directory.

    Args:
        output_dir (Path): The directory that should contain the bundle folder.
        skip_pip_upgrade (bool): Whether to skip upgrading pip first.

    Returns:
        Path: The generated bundle directory.
    """
    repo_root: Path = Path(__file__).resolve().parents[3]
    bundle_name: str = build_bundle_name(
        platform.system(),
        platform.machine(),
        sys.version_info.major,
        sys.version_info.minor,
    )
    bundle_dir: Path = output_dir / bundle_name
    wheelhouse_dir: Path = bundle_dir / WHEELHOUSE_DIRNAME

    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    wheelhouse_dir.mkdir(parents=True, exist_ok=True)

    pip_prefix: list[str] = [sys.executable, '-m', 'pip']
    if not skip_pip_upgrade:
        run_command(
            [*pip_prefix, 'install', '--upgrade', f'pip=={PIP_VERSION}'],
            repo_root,
        )

    run_command(
        [
            *pip_prefix,
            'download',
            '--dest',
            str(wheelhouse_dir),
            '--only-binary=:all:',
            f'pip=={PIP_VERSION}',
        ],
        repo_root,
    )

    run_command(
        [
            *pip_prefix,
            'wheel',
            '--wheel-dir',
            str(wheelhouse_dir),
            '-r',
            'requirements/runtime.lock',
        ],
        repo_root,
    )
    run_command(
        [
            *pip_prefix,
            'wheel',
            '--wheel-dir',
            str(wheelhouse_dir),
            '--no-deps',
            '.',
        ],
        repo_root,
    )

    write_text_file(bundle_dir / INSTALL_GUIDE_NAME, build_install_guide(bundle_name))
    write_executable_text_file(
        bundle_dir / INSTALL_SHELL_NAME,
        build_install_shell_script(),
    )
    write_text_file(
        bundle_dir / INSTALL_WINDOWS_NAME,
        build_install_windows_script(),
    )
    write_text_file(bundle_dir / CHECKSUM_FILE_NAME, build_sha256_manifest(bundle_dir))
    archive_path: Path = archive_bundle(bundle_dir)

    print(f'Bundle directory: {bundle_dir}')
    print(f'Bundle archive: {archive_path}')
    return bundle_dir


def parse_args() -> argparse.Namespace:
    """
    Parses CLI arguments for the release wheelhouse builder.

    Args:
        None

    Returns:
        argparse.Namespace: The parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description='Build one release wheel bundle for the current platform.'
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help='Directory that will receive the bundle folder and zip archive.',
    )
    parser.add_argument(
        '--skip-pip-upgrade',
        action='store_true',
        help='Skip upgrading pip before building wheels.',
    )
    return parser.parse_args()


def main() -> None:
    """
    Builds the release wheel bundle for the current host platform.

    Args:
        None

    Returns:
        None
    """
    args = parse_args()
    build_release_wheelhouse(args.output_dir, skip_pip_upgrade=args.skip_pip_upgrade)
