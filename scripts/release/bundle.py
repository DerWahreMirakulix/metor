"""Repository tooling for building platform-specific release wheel bundles."""

import argparse
import json
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from textwrap import dedent
from typing import Sequence

from scripts.release.paths import PROJECT_ROOT
from scripts.release.verify_bundle import bundle_payloads, file_digest


PIP_VERSION: str = '26.2.1'
DEFAULT_OUTPUT_DIR: Path = Path('dist') / 'release'
WHEELHOUSE_DIRNAME: str = 'wheelhouse'
INSTALL_GUIDE_NAME: str = 'INSTALL.txt'
INSTALL_SHELL_NAME: str = 'install.sh'
INSTALL_WINDOWS_NAME: str = 'install.cmd'
CHECKSUM_FILE_NAME: str = 'SHA256SUMS.txt'
BUNDLE_METADATA_NAME: str = 'BUNDLE.json'
BUNDLE_VERIFIER_NAME: str = 'verify_bundle.py'
RELEASE_VARIANTS: tuple[str, ...] = ('base', 'terminal', 'sdk', 'gui')
LOCAL_WHEEL_SOURCES: tuple[tuple[str, str], ...] = (
    ('packaging/sdk', 'metor_sdk-'),
    ('.', 'metor-'),
    ('packaging/terminal', 'metor_ui_terminal-'),
    ('packaging/gui', 'metor_ui_gui-'),
)


def packaging_build_roots(repo_root: Path) -> tuple[Path, ...]:
    """Returns setuptools output roots for the four local distributions."""
    return tuple(repo_root / source / 'build' for source, _ in LOCAL_WHEEL_SOURCES)


def is_packaging_build_directory(name: str) -> bool:
    """Identifies setuptools-owned children without claiming other build output."""
    return name == 'lib' or name.startswith(('lib.', 'bdist.', 'temp.'))


def validate_output_directory(output_dir: Path, repo_root: Path) -> Path:
    """Rejects bundle destinations that subsequent packaging cleanup would erase."""
    destination = output_dir.resolve()
    for build_root in packaging_build_roots(repo_root):
        try:
            relative = destination.relative_to(build_root.resolve())
        except ValueError:
            continue
        if relative.parts and is_packaging_build_directory(relative.parts[0]):
            raise ValueError('Release output cannot use a setuptools build directory.')
    return destination


def clean_packaging_artifacts(repo_root: Path) -> None:
    """Removes stale local packaging outputs before building release wheels.

    Args:
        repo_root (Path): The repository root containing generated packaging artifacts.

    Returns:
        None
    """
    # Build also holds test reports and user-selected release output. Only
    # setuptools owns these specific children; never delete the entire root.
    for build_root in packaging_build_roots(repo_root):
        if build_root.is_dir():
            for child in build_root.iterdir():
                if is_packaging_build_directory(child.name):
                    shutil.rmtree(child, ignore_errors=True)
    shutil.rmtree(repo_root / 'src' / 'metor.egg-info', ignore_errors=True)
    shutil.rmtree(repo_root / 'src' / 'metor_sdk.egg-info', ignore_errors=True)
    shutil.rmtree(repo_root / 'src' / 'metor_ui_terminal.egg-info', ignore_errors=True)
    shutil.rmtree(repo_root / 'src' / 'metor_ui_gui.egg-info', ignore_errors=True)


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
    variant: str = 'base',
) -> str:
    """
    Builds the release bundle folder name for one platform, Python version, and variant.

    Args:
        system_name (str): The host operating system name.
        machine (str): The host architecture label.
        python_major (int): The Python major version.
        python_minor (int): The Python minor version.
        variant (str): The distribution variant ('base', 'terminal', 'gui', or 'sdk').

    Returns:
        str: The bundle directory name.
    """
    if variant not in RELEASE_VARIANTS:
        raise ValueError(f'Unsupported release variant: {variant}.')
    system_slug: str = system_name.strip().lower() or 'unknown'
    machine_slug: str = normalize_machine(machine)
    prefix: str = 'metor-wheelhouse'
    if variant == 'terminal':
        prefix = 'metor-ui-terminal-wheelhouse'
    elif variant == 'sdk':
        prefix = 'metor-sdk-wheelhouse'
    elif variant == 'gui':
        prefix = 'metor-ui-gui-wheelhouse'

    return f'{prefix}-{system_slug}-{machine_slug}-py{python_major}{python_minor}'


def build_install_guide(bundle_name: str, package_name: str = 'metor') -> str:
    """
    Builds the human-readable offline installation guide for one bundle.

    Args:
        bundle_name (str): The generated bundle directory name.
        package_name (str): The package to install from the wheelhouse.

    Returns:
        str: The installation guide text.
    """
    gui_start: str = (
        'For a console-free Windows GUI start, open .venv\\Scripts\\metor-gui.exe.\n'
        if package_name == 'metor-ui-gui'
        else ''
    )
    return dedent(
        f"""\
        Metor release bundle: {bundle_name}

        This archive contains the {package_name} wheel plus all Python runtime wheels
        required for this host platform. Install Tor separately from the
        official Tor Project sources.

        Simplest installation:

          Linux:   sh {INSTALL_SHELL_NAME}
          Windows: {INSTALL_WINDOWS_NAME}

        Extract into a fresh directory for every installation. Both scripts
        refuse an existing .venv and install {package_name} from the wheelhouse.
        Use an installed interpreter on PATH outside the extracted directory.

        Manual fallback on Linux:

          export PIP_CONFIG_FILE=/dev/null

          PYTHON=/absolute/path/to/python{sys.version_info.major}.{sys.version_info.minor}
          "$PYTHON" -I -S {BUNDLE_VERIFIER_NAME} . &&
          mkdir .venv &&
          "$PYTHON" -I -m venv .venv &&
          .venv/bin/python -I -m pip --isolated --require-virtualenv install --no-index --find-links wheelhouse --upgrade pip=={PIP_VERSION} &&
          .venv/bin/python -I -m pip --isolated --require-virtualenv install --no-index --find-links wheelhouse {package_name}

        On Windows PowerShell, use:

          $env:PIP_CONFIG_FILE = "nul"

          $python = 'C:\\path\\to\\installed\\python.exe'
          & $python -I -S {BUNDLE_VERIFIER_NAME} .
          if ($LASTEXITCODE) {{ throw 'Bundle verification failed' }}
          New-Item -ItemType Directory -Path .venv -ErrorAction Stop | Out-Null
          & $python -I -m venv .venv
          if ($LASTEXITCODE) {{ throw 'Environment creation failed' }}
          .venv\\Scripts\\python.exe -I -m pip --isolated --require-virtualenv install --no-index --find-links wheelhouse --upgrade pip=={PIP_VERSION}
          if ($LASTEXITCODE) {{ throw 'Offline pip installation failed' }}
          .venv\\Scripts\\python.exe -I -m pip --isolated --require-virtualenv install --no-index --find-links wheelhouse {package_name}

        The --no-index flag ensures installation stays inside this bundle,
        requires no package index access, and never falls back to building
        native extensions on the target host.

        The installers verify SHA256SUMS.txt, including the bundled pip wheel,
        before changing .venv. These hashes detect incomplete or modified bundle
        contents; they are not a signature or publisher-authenticity proof.
        {gui_start}
        """
    )


def build_install_shell_script(package_name: str = 'metor') -> str:
    """
    Builds the Linux shell installer shipped inside one release bundle.

    Args:
        package_name (str): Name of the package to install.

    Returns:
        str: The shell installer script.
    """
    verification_line: str = (
        'echo "Run $venv_dir/bin/metor --help to verify the install."'
        if package_name != 'metor-sdk'
        else 'echo "Run $venv_dir/bin/python -c \\"import metor.client; print(\'metor-sdk ready\')\\" to verify the install."'
    )
    return dedent(
        f"""\
        #!/usr/bin/env sh
        set -eu
        export PIP_CONFIG_FILE=/dev/null

        case "$0" in
          */*) directory=${{0%/*}}; directory=${{directory:-/}} ;;
          *) directory=. ;;
        esac
        script_dir=$(CDPATH= cd -P -- "$directory" && pwd -P)
        venv_dir="$script_dir/.venv"
        python_bin=''

        if [ -e "$venv_dir" ] || [ -L "$venv_dir" ]; then
          echo 'Existing .venv; extract the archive into a fresh directory.' >&2
          exit 1
        fi

        # Only search absolute PATH directories outside the extracted bundle.
        safe_path=''
        remaining=$PATH:
        while [ -n "$remaining" ]; do
          entry=${{remaining%%:*}}
          remaining=${{remaining#*:}}
          case "$entry" in /*) ;; *) continue ;; esac
          entry=$(CDPATH= cd -P -- "$entry" 2>/dev/null && pwd -P) || continue
          case "$entry/" in "$script_dir/"*) continue ;; esac
          safe_path=${{safe_path:+$safe_path:}}$entry
        done
        [ -n "$safe_path" ] || {{ echo 'No external interpreter directory on PATH.' >&2; exit 1; }}
        PATH=$safe_path
        export PATH
        for candidate in python{sys.version_info.major}.{sys.version_info.minor} python3 python; do
          if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -I -S "$script_dir/{BUNDLE_VERIFIER_NAME}" "$script_dir" --target-only >/dev/null 2>&1; then
            python_bin="$candidate"
            break
          fi
        done

        if [ -z "$python_bin" ]; then
          echo 'No interpreter matches this bundle target.' >&2
          exit 1
        fi

        "$python_bin" -I -S "$script_dir/{BUNDLE_VERIFIER_NAME}" "$script_dir"
        mkdir -- "$venv_dir"
        "$python_bin" -I -m venv "$venv_dir"
        "$venv_dir/bin/python" -I -m pip --isolated --require-virtualenv install --no-index --find-links "$script_dir/{WHEELHOUSE_DIRNAME}" --upgrade pip=={PIP_VERSION}
        "$venv_dir/bin/python" -I -m pip --isolated --require-virtualenv install --no-index --find-links "$script_dir/{WHEELHOUSE_DIRNAME}" {package_name}

        echo "{package_name} installed in $venv_dir"
        {verification_line}
        """
    )


def build_install_windows_script(package_name: str = 'metor') -> str:
    """Builds the Windows batch installer shipped inside one release bundle.

    Args:
        package_name: Name of the package to install.

    Returns:
        str: The Windows batch installer script.
    """
    if package_name == 'metor-ui-gui':
        verification_line = (
            'echo Open "%VENV_DIR%\\Scripts\\metor-gui.exe" to start the GUI.'
        )
    elif package_name != 'metor-sdk':
        verification_line = (
            'echo Run "%VENV_DIR%\\Scripts\\metor.exe --help" to verify the install.'
        )
    else:
        verification_line = 'echo metor-sdk ready in "%VENV_DIR%"'
    return dedent(
        f"""\
        @echo off
        setlocal DisableDelayedExpansion
        set "PIP_CONFIG_FILE=nul"
        for %%D in ("%~dp0.") do set "BUNDLE_DIR=%%~fD"
        for %%D in ("%BUNDLE_DIR%") do set "BUNDLE_KEY=%%~fsD"
        set "VENV_DIR=%BUNDLE_DIR%\\.venv"
        set "VERIFY=%BUNDLE_DIR%\\{BUNDLE_VERIFIER_NAME}"
        pushd "%SystemRoot%\\System32" || exit /b 1
        if exist "%VENV_DIR%" goto existing_venv
        for %%V in ("%VENV_DIR%") do if not "%%~aV"=="" goto existing_venv

        set "PY_OPTION=-{sys.version_info.major}.{sys.version_info.minor}"
        for /f "delims=" %%P in ('.\\where.exe $PATH:py.exe 2^>nul') do (
            set "PYTHON_EXE=%%P"
            call :probe
            if not errorlevel 1 goto selected
        )
        set "PY_OPTION="
        for /f "delims=" %%P in ('.\\where.exe $PATH:python.exe 2^>nul') do (
            set "PYTHON_EXE=%%P"
            call :probe
            if not errorlevel 1 goto selected
        )
        echo No interpreter matches this bundle target.
        goto failed

        :probe
        rem Reject candidates anywhere under the extracted directory, including PATH entries.
        for %%D in ("%PYTHON_EXE%") do set "CHECK_DIR=%%~dpD."
        :check_parent
        for %%D in ("%CHECK_DIR%") do set "CHECK_DIR=%%~fD"
        for %%D in ("%CHECK_DIR%") do if /i "%%~fsD"=="%BUNDLE_KEY%" exit /b 1
        for %%D in ("%CHECK_DIR%\\..") do set "PARENT_DIR=%%~fD"
        if /i "%CHECK_DIR%"=="%PARENT_DIR%" goto probe_target
        set "CHECK_DIR=%PARENT_DIR%"
        goto check_parent
        :probe_target
        "%PYTHON_EXE%" %PY_OPTION% -I -S "%VERIFY%" "%BUNDLE_DIR%" --target-only >nul 2>nul
        exit /b %errorlevel%

        :selected
        "%PYTHON_EXE%" %PY_OPTION% -I -S "%VERIFY%" "%BUNDLE_DIR%" || goto failed
        mkdir "%VENV_DIR%" || goto existing_venv
        "%PYTHON_EXE%" %PY_OPTION% -I -m venv "%VENV_DIR%" || goto failed
        "%VENV_DIR%\\Scripts\\python.exe" -I -m pip --isolated --require-virtualenv install --no-index --find-links "%BUNDLE_DIR%\\{WHEELHOUSE_DIRNAME}" --upgrade pip=={PIP_VERSION} || goto failed
        "%VENV_DIR%\\Scripts\\python.exe" -I -m pip --isolated --require-virtualenv install --no-index --find-links "%BUNDLE_DIR%\\{WHEELHOUSE_DIRNAME}" {package_name} || goto failed
        echo Metor installed in "%VENV_DIR%"
        {verification_line}
        popd
        exit /b 0
        :existing_venv
        echo Existing .venv; extract the archive into a fresh directory. 1>&2
        :failed
        popd
        exit /b 1
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


def build_sha256_manifest(bundle_dir: Path) -> str:
    """
    Builds the SHA256 checksum manifest for one release bundle.

    Args:
        bundle_dir (Path): The bundle directory to hash.

    Returns:
        str: The checksum manifest contents.
    """
    lines: list[str] = []
    for file_path in sorted(bundle_payloads(bundle_dir)):
        digest = file_digest(file_path)
        relative_path: str = file_path.relative_to(bundle_dir).as_posix()
        lines.append(f'{digest}  {relative_path}')
    return '\n'.join(lines) + '\n'


def build_bundle_metadata(variant: str, package_name: str) -> str:
    """Builds exact interpreter and host metadata for one native wheelhouse.

    Args:
        variant: Release bundle variant.
        package_name: Explicit distribution installed by the bundle.

    Returns:
        str: Deterministic JSON target metadata.
    """
    document = {
        'abi': sys.implementation.cache_tag,
        'machine': normalize_machine(platform.machine()),
        'package': package_name,
        'python': f'{sys.version_info.major}.{sys.version_info.minor}',
        'schema': 1,
        'system': platform.system().strip().lower(),
        'variant': variant,
    }
    return json.dumps(document, indent=2, sort_keys=True) + '\n'


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
    variant: str = 'base',
    prebuilt_wheels: dict[str, Path] | None = None,
) -> Path:
    """
    Builds the platform-specific runtime wheel bundle in the target directory.

    Args:
        output_dir (Path): The directory that should contain the bundle folder.
        skip_pip_upgrade (bool): Whether to skip upgrading pip first.
        variant (str): The distribution variant ('base', 'terminal', 'gui', or 'sdk').
        prebuilt_wheels: Exact local wheels built once for an all-variant run.

    Returns:
        Path: The generated bundle directory.
    """
    if variant not in RELEASE_VARIANTS:
        raise ValueError(f'Unsupported release variant: {variant}.')
    repo_root: Path = PROJECT_ROOT
    output_dir = validate_output_directory(output_dir, repo_root)
    bundle_name: str = build_bundle_name(
        platform.system(),
        platform.machine(),
        sys.version_info.major,
        sys.version_info.minor,
        variant=variant,
    )
    bundle_dir: Path = output_dir / bundle_name
    wheelhouse_dir: Path = bundle_dir / WHEELHOUSE_DIRNAME

    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    wheelhouse_dir.mkdir(parents=True, exist_ok=True)
    clean_packaging_artifacts(repo_root)

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

    wheel_sources: tuple[str, ...]
    if variant == 'sdk':
        req_lock = 'requirements/sdk.lock'
        package_name = 'metor-sdk'
        wheel_sources = ('packaging/sdk',)
    elif variant == 'terminal':
        req_lock = 'requirements/terminal.lock'
        package_name = 'metor-ui-terminal'
        wheel_sources = ('packaging/sdk', '.', 'packaging/terminal')
    elif variant == 'gui':
        req_lock = 'requirements/gui.lock'
        package_name = 'metor-ui-gui'
        wheel_sources = ('packaging/sdk', '.', 'packaging/gui')
    else:
        req_lock = 'requirements/base.lock'
        package_name = 'metor'
        wheel_sources = ('packaging/sdk', '.')

    run_command(
        [
            *pip_prefix,
            'wheel',
            '--wheel-dir',
            str(wheelhouse_dir),
            '-r',
            req_lock,
        ],
        repo_root,
    )
    for wheel_src in wheel_sources:
        if prebuilt_wheels is not None:
            shutil.copy2(prebuilt_wheels[wheel_src], wheelhouse_dir)
        else:
            run_command(
                [
                    *pip_prefix,
                    'wheel',
                    '--wheel-dir',
                    str(wheelhouse_dir),
                    '--no-deps',
                    wheel_src,
                ],
                repo_root,
            )

    write_text_file(
        bundle_dir / INSTALL_GUIDE_NAME,
        build_install_guide(bundle_name, package_name),
    )
    write_executable_text_file(
        bundle_dir / INSTALL_SHELL_NAME,
        build_install_shell_script(package_name),
    )
    write_text_file(
        bundle_dir / INSTALL_WINDOWS_NAME,
        build_install_windows_script(package_name),
    )
    write_text_file(
        bundle_dir / BUNDLE_METADATA_NAME,
        build_bundle_metadata(variant, package_name),
    )
    shutil.copyfile(
        repo_root / 'scripts' / 'release' / BUNDLE_VERIFIER_NAME,
        bundle_dir / BUNDLE_VERIFIER_NAME,
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
    parser.add_argument(
        '--variant',
        choices=(*RELEASE_VARIANTS, 'all'),
        default='base',
        help='Distribution bundle variant to build.',
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
    args.output_dir = validate_output_directory(args.output_dir, PROJECT_ROOT)
    if args.variant == 'all':
        with tempfile.TemporaryDirectory(prefix='metor-local-wheels-') as directory:
            wheel_dir = Path(directory)
            clean_packaging_artifacts(PROJECT_ROOT)
            for source, _prefix in LOCAL_WHEEL_SOURCES:
                run_command(
                    [
                        sys.executable,
                        '-m',
                        'pip',
                        'wheel',
                        '--wheel-dir',
                        str(wheel_dir),
                        '--no-deps',
                        source,
                    ],
                    PROJECT_ROOT,
                )
            prebuilt: dict[str, Path] = {}
            for source, prefix in LOCAL_WHEEL_SOURCES:
                matches = tuple(wheel_dir.glob(f'{prefix}*.whl'))
                if len(matches) != 1:
                    raise RuntimeError(f'Expected one built wheel for {source}.')
                prebuilt[source] = matches[0]
            for variant in RELEASE_VARIANTS:
                build_release_wheelhouse(
                    args.output_dir,
                    skip_pip_upgrade=args.skip_pip_upgrade,
                    variant=variant,
                    prebuilt_wheels=prebuilt,
                )
    else:
        build_release_wheelhouse(
            args.output_dir,
            skip_pip_upgrade=args.skip_pip_upgrade,
            variant=args.variant,
        )
