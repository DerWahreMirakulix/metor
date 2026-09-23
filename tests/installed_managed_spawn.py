"""Installed-wheel proof for the real managed encrypted-daemon spawn path."""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import venv

import psutil

import metor.application as metor_application
from metor.application import DaemonStartDiagnostics, start_managed_daemon_process
from metor.data import ProfileManager, ProfileSecurityMode, SettingKey, Settings
from metor.utils import Constants, ProcessManager


_PUBLIC_STARTUP_SENTINEL = 'public-installed-startup-sentinel'
_MANAGED_START_TIMEOUT_SEC: float = 45.0
_MANAGED_DIAGNOSTIC_MAX_BYTES: int = 4096


def _same_filesystem_object(left: Path, right: Path) -> bool:
    """Compares existing paths by identity across aliases and short names."""
    try:
        return left.samefile(right)
    except OSError:
        return left.resolve() == right.resolve()


def _expected_interpreter_files(executable: Path) -> tuple[Path, ...]:
    """Returns the exact interpreter files allowed for the spawned daemon.

    Windows virtual-environment launchers can hand execution to their configured
    base interpreter. Both files belong to the selected environment; no other
    executable is accepted.

    Args:
        executable (Path): Virtual-environment interpreter selected by the probe.

    Returns:
        tuple[Path, ...]: Selected interpreter and its Windows base interpreter.
    """
    selected = [executable.resolve()]
    base_executable = getattr(sys, '_base_executable', None)
    if os.name == 'nt' and isinstance(base_executable, str) and base_executable:
        base_path = Path(base_executable).resolve()
        if not any(_same_filesystem_object(base_path, current) for current in selected):
            selected.append(base_path)
    return tuple(selected)


def _is_within_filesystem_root(path: Path, root: Path) -> bool:
    """Checks containment by directory identity rather than path spelling."""
    return any(
        _same_filesystem_object(candidate, root) for candidate in (path, *path.parents)
    )


def _sanitized_child_output(payload: bytes, redactions: tuple[str, ...]) -> str:
    """Decodes bounded child output and removes known acceptance-only values.

    Args:
        payload (bytes): Bounded stdout/stderr bytes from the owned child.
        redactions (tuple[str, ...]): Exact public or temporary values to remove.

    Returns:
        str: Sanitized diagnostic text without acceptance credentials or host paths.
    """
    rendered = payload.decode('utf-8', errors='replace')
    for value in redactions:
        if value:
            rendered = rendered.replace(value, '<redacted>')
    return rendered


def _runtime_file_evidence(path: Path) -> tuple[bool, int | None]:
    """Returns stable, non-content evidence for one runtime state path.

    Args:
        path (Path): Runtime state path to inspect without following aliases.

    Returns:
        tuple[bool, int | None]: Presence and size from one metadata lookup.
    """
    try:
        info = path.lstat()
    except OSError:
        return False, None
    return True, info.st_size


def _stop_owned_process(pid: int) -> None:
    """Stops only the exact child created and identity-checked by this probe."""
    process = psutil.Process(pid)
    process.terminate()
    try:
        process.wait(timeout=Constants.TOR_KILL_TIMEOUT_SEC)
    except psutil.TimeoutExpired:
        process.kill()
        process.wait(timeout=Constants.TOR_KILL_TIMEOUT_SEC)


def _create_profile(
    profile_name: str,
    security_mode: ProfileSecurityMode,
) -> ProfileManager:
    """Creates one isolated profile for an installed managed-start scenario.

    Args:
        profile_name (str): Exact profile identity for the scenario.
        security_mode (ProfileSecurityMode): Storage mode required by the scenario.

    Returns:
        ProfileManager: Manager for the newly created profile.
    """
    if security_mode is ProfileSecurityMode.PLAINTEXT:
        Settings.set(SettingKey.ALLOW_PLAINTEXT_PROFILES, True)
    result = ProfileManager.add_profile_folder(
        profile_name,
        security_mode=security_mode,
        master_password=(
            'temporary-installed-spawn-password'
            if security_mode is ProfileSecurityMode.ENCRYPTED
            else None
        ),
    )
    if not result.success:
        raise AssertionError(result)
    return ProfileManager(profile_name)


def _verify_missing_installation_fails_closed(
    data_parent: Path,
    shadow_directory: Path,
    shadow_marker: Path,
) -> None:
    """Proves isolated module startup cannot fall back to a cwd/PYTHONPATH shadow.

    Args:
        data_parent (Path): Temporary acceptance root that owns the bare environment.
        shadow_directory (Path): Working directory containing the hostile shadow.
        shadow_marker (Path): Marker written only if the shadow package executes.

    Returns:
        None
    """
    environment_root = data_parent / 'missing-installation-environment'
    venv.EnvBuilder(with_pip=False).create(environment_root)
    executable = environment_root / (
        'Scripts/python.exe' if os.name == 'nt' else 'bin/python'
    )
    environment = dict(os.environ)
    environment['PYTHONPATH'] = str(shadow_directory)
    result = subprocess.run(
        [str(executable), '-I', '-m', 'metor', '--version'],
        cwd=shadow_directory,
        env=environment,
        input=_PUBLIC_STARTUP_SENTINEL,
        capture_output=True,
        text=True,
        timeout=_MANAGED_START_TIMEOUT_SEC,
        check=False,
    )
    if result.returncode == 0:
        raise AssertionError('missing installed module unexpectedly started')
    if shadow_marker.exists():
        raise AssertionError('missing installation fell back to the shadow package')
    print(
        'MISSING_INSTALLED_MODULE_FAILS_CLOSED',
        json.dumps({'return_code': result.returncode}, sort_keys=True),
        flush=True,
    )


def _run_installed_start(
    profile: ProfileManager,
    *,
    checkout: Path,
    environment_root: Path,
    executable: Path,
    working_directory: Path,
    start_locked: bool,
    session_auth_password: str | None,
    shadow_marker: Path,
) -> None:
    """Proves one real child uses the selected installation and exact launch form.

    Args:
        profile (ProfileManager): Installed profile selected for startup.
        checkout (Path): Source checkout that must not supply child modules.
        environment_root (Path): Selected virtual-environment root.
        executable (Path): Exact interpreter invocation path.
        working_directory (Path): Arbitrary directory inherited by the child.
        start_locked (bool): Whether to use locked encrypted startup.
        session_auth_password (str | None): Optional public session-auth sentinel.
        shadow_marker (Path): Marker written only if the shadow package executes.

    Returns:
        None
    """
    previous_directory = Path.cwd()
    pid: int | None = None
    port: int | None = None
    diagnostic_stream = None
    diagnostic_path = working_directory / 'managed-child-diagnostic.log'
    diagnostics = DaemonStartDiagnostics()
    started_at: float = time.monotonic()
    try:
        diagnostic_stream = diagnostic_path.open('w+b')
        profile.config.set(SettingKey.IPC_TIMEOUT, _MANAGED_START_TIMEOUT_SEC)
        os.chdir(working_directory)
        print(
            'INSTALLED_MANAGED_SPAWN_START',
            json.dumps(
                {
                    'profile': profile.profile_name,
                    'start_locked': start_locked,
                    'startup_secret': session_auth_password is not None,
                    'timeout_seconds': _MANAGED_START_TIMEOUT_SEC,
                    'working_directory': working_directory.name,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        started = start_managed_daemon_process(
            profile,
            start_locked=start_locked,
            session_auth_password=session_auth_password,
            diagnostics=diagnostics,
            diagnostic_output=diagnostic_stream,
        )
        if shadow_marker.exists():
            raise AssertionError(
                f'shadow Metor package executed: {shadow_marker.read_text(encoding="utf-8")!r}'
            )
        if not started:
            diagnostic_stream.flush()
            diagnostic_stream.seek(0)
            child_output = diagnostic_stream.read(_MANAGED_DIAGNOSTIC_MAX_BYTES + 1)
            output_truncated = len(child_output) > _MANAGED_DIAGNOSTIC_MAX_BYTES
            child_output = child_output[:_MANAGED_DIAGNOSTIC_MAX_BYTES]
            pid_path: Path = profile.paths.get_daemon_pid_file()
            port_path: Path = profile.paths.get_daemon_port_file()
            pid_exists, pid_size = _runtime_file_evidence(pid_path)
            port_exists, port_size = _runtime_file_evidence(port_path)
            raise AssertionError(
                'managed child did not publish IPC readiness: '
                + json.dumps(
                    {
                        'elapsed_seconds': round(time.monotonic() - started_at, 3),
                        'child_output': _sanitized_child_output(
                            child_output,
                            (
                                session_auth_password or '',
                                str(checkout),
                                str(environment_root),
                                str(executable.parents[1]),
                                str(working_directory),
                                str(Path.home()),
                            ),
                        ),
                        'child_output_truncated': output_truncated,
                        'child_pid': diagnostics.child_pid,
                        'child_return_code': diagnostics.return_code,
                        'launch_phase': diagnostics.phase,
                        'pid_file_exists': pid_exists,
                        'pid_file_size': pid_size,
                        'port_file_exists': port_exists,
                        'port_file_size': port_size,
                        'profile': profile.profile_name,
                        'start_locked': start_locked,
                        'trusted_pid': profile.get_daemon_pid(),
                    },
                    sort_keys=True,
                )
            )
        port = profile.get_daemon_port()
        pid = profile.get_daemon_pid()
        if port is None or pid is None:
            raise AssertionError((port, pid))

        with socket.create_connection((Constants.LOCALHOST, port), timeout=2):
            pass

        identity_path = profile.paths.get_daemon_pid_file()
        identity = json.loads(identity_path.read_text(encoding='utf-8'))
        expected_installation = str(ProcessManager._installation_root())
        if identity['profile'] != profile.profile_name:
            raise AssertionError(identity)
        if identity['installation_root'] != expected_installation:
            raise AssertionError(identity)
        if not _is_within_filesystem_root(
            Path(expected_installation), environment_root
        ):
            raise AssertionError(expected_installation)

        child = psutil.Process(pid)
        command = child.cmdline()
        expected_interpreters = _expected_interpreter_files(executable)
        if not command or not any(
            _same_filesystem_object(Path(command[0]), candidate)
            for candidate in expected_interpreters
        ):
            raise AssertionError(command)
        if command[1:4] != ['-I', '-m', 'metor']:
            raise AssertionError(command)
        if profile.profile_name not in command:
            raise AssertionError(command)
        if start_locked != ('--locked' in command):
            raise AssertionError(command)
        if (session_auth_password is not None) != (
            '--startup-session-auth-stdin' in command
        ):
            raise AssertionError(command)
        child_directory = Path(child.cwd()).resolve()
        if not _same_filesystem_object(child_directory, working_directory):
            raise AssertionError(child_directory)
        if _is_within_filesystem_root(child_directory, checkout):
            raise AssertionError(f'child cwd remained in checkout: {child_directory}')

        print(
            'INSTALLED_MANAGED_SPAWN_OK',
            json.dumps(
                {
                    'executable': str(executable),
                    'installation_root': expected_installation,
                    'module': str(Path(metor_application.__file__).resolve()),
                    'pid': pid,
                    'port': port,
                    'profile': profile.profile_name,
                    'start_locked': start_locked,
                    'startup_secret': session_auth_password is not None,
                    'working_directory': working_directory.name,
                },
                sort_keys=True,
            ),
            flush=True,
        )
    finally:
        os.chdir(previous_directory)
        if pid is not None:
            try:
                identity_pid = profile.get_daemon_pid()
                if identity_pid == pid and psutil.pid_exists(pid):
                    _stop_owned_process(pid)
            finally:
                deadline = time.monotonic() + Constants.TOR_KILL_TIMEOUT_SEC
                while psutil.pid_exists(pid) and time.monotonic() < deadline:
                    time.sleep(Constants.LOCK_SLEEP_SEC)
                profile.clear_daemon_port(expected_pid=pid, expected_port=port)
        ProcessManager.cleanup_processes()
        if diagnostic_stream is not None:
            diagnostic_stream.close()
        diagnostic_path.unlink(missing_ok=True)


def run(data_parent: Path, checkout: Path) -> None:
    """Proves installed locked and session-auth starts ignore import shadows.

    Args:
        data_parent (Path): Isolated parent for Metor runtime data and fixtures.
        checkout (Path): Source checkout that must not supply installed modules.

    Returns:
        None
    """
    data_parent = data_parent.resolve()
    checkout = checkout.resolve()
    module_path = Path(metor_application.__file__).resolve()
    environment_root = Path(sys.prefix).resolve()
    executable = Path(sys.executable)
    if checkout in module_path.parents:
        raise AssertionError(f'loaded Metor from checkout: {module_path}')
    if environment_root not in module_path.parents:
        raise AssertionError(f'Metor is outside selected environment: {module_path}')
    expected_executable = environment_root / (
        'Scripts/python.exe' if os.name == 'nt' else 'bin/python'
    )
    if not _same_filesystem_object(executable, expected_executable):
        raise AssertionError(
            f'interpreter is outside selected environment: {executable}'
        )
    if os.name != 'nt' and executable.resolve() == executable:
        raise AssertionError('acceptance venv interpreter is not symlink-based')

    expected_data = data_parent / Constants.DATA_DIR
    if Constants.DATA.resolve() != expected_data:
        raise AssertionError((Constants.DATA, expected_data))

    ordinary_directory = data_parent / 'ordinary-working-directory'
    shadow_directory = data_parent / 'shadow-working-directory'
    shadow_package = shadow_directory / 'metor'
    shadow_marker = data_parent / 'shadow-executed.txt'
    ordinary_directory.mkdir()
    shadow_package.mkdir(parents=True)
    (shadow_package / '__init__.py').write_text('', encoding='utf-8')
    (shadow_package / '__main__.py').write_text(
        'from pathlib import Path\n'
        'import sys\n'
        f'Path({str(shadow_marker)!r}).write_text(sys.stdin.readline(), encoding="utf-8")\n',
        encoding='utf-8',
    )
    os.environ['PYTHONPATH'] = str(shadow_directory)
    _verify_missing_installation_fails_closed(
        data_parent,
        shadow_directory,
        shadow_marker,
    )

    locked_profile = _create_profile(
        'installed-managed-locked',
        ProfileSecurityMode.ENCRYPTED,
    )
    _run_installed_start(
        locked_profile,
        checkout=checkout,
        environment_root=environment_root,
        executable=executable,
        working_directory=ordinary_directory,
        start_locked=True,
        session_auth_password=None,
        shadow_marker=shadow_marker,
    )

    plaintext_profile = _create_profile(
        'installed-managed-session-auth',
        ProfileSecurityMode.PLAINTEXT,
    )
    _run_installed_start(
        plaintext_profile,
        checkout=checkout,
        environment_root=environment_root,
        executable=executable,
        working_directory=shadow_directory,
        start_locked=False,
        session_auth_password=_PUBLIC_STARTUP_SENTINEL,
        shadow_marker=shadow_marker,
    )


def main() -> None:
    """Parses isolated acceptance paths and runs the installed spawn proof."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-parent', required=True, type=Path)
    parser.add_argument('--checkout', required=True, type=Path)
    args = parser.parse_args()
    run(args.data_parent, args.checkout)


if __name__ == '__main__':
    main()
