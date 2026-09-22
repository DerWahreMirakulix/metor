"""Installed-wheel proof for the real managed encrypted-daemon spawn path."""

import argparse
import json
import os
from pathlib import Path
import socket
import sys
import time

import psutil

import metor.application as metor_application
from metor.application import start_managed_daemon_process
from metor.data import ProfileManager, ProfileSecurityMode
from metor.utils import Constants, ProcessManager


def _stop_owned_process(pid: int) -> None:
    """Stops only the exact child created and identity-checked by this probe."""
    process = psutil.Process(pid)
    process.terminate()
    try:
        process.wait(timeout=Constants.TOR_KILL_TIMEOUT_SEC)
    except psutil.TimeoutExpired:
        process.kill()
        process.wait(timeout=Constants.TOR_KILL_TIMEOUT_SEC)


def run(data_parent: Path, checkout: Path) -> None:
    """Creates a locked profile and proves installed managed-child provenance."""
    data_parent = data_parent.resolve()
    checkout = checkout.resolve()
    module_path = Path(metor_application.__file__).resolve()
    environment_root = Path(sys.prefix).resolve()
    executable = Path(sys.executable)
    if checkout in module_path.parents:
        raise AssertionError(f'loaded Metor from checkout: {module_path}')
    if environment_root not in module_path.parents:
        raise AssertionError(f'Metor is outside selected environment: {module_path}')
    if environment_root not in executable.parents:
        raise AssertionError(
            f'interpreter is outside selected environment: {executable}'
        )
    if os.name != 'nt' and executable.resolve() == executable:
        raise AssertionError('acceptance venv interpreter is not symlink-based')

    expected_data = data_parent / Constants.DATA_DIR
    if Constants.DATA.resolve() != expected_data:
        raise AssertionError((Constants.DATA, expected_data))
    profile_name = 'installed-managed-spawn'
    result = ProfileManager.add_profile_folder(
        profile_name,
        security_mode=ProfileSecurityMode.ENCRYPTED,
        master_password='temporary-installed-spawn-password',
    )
    if not result.success:
        raise AssertionError(result)
    profile = ProfileManager(profile_name)
    pid: int | None = None
    port: int | None = None
    try:
        if not start_managed_daemon_process(profile, start_locked=True):
            raise AssertionError('managed child did not publish IPC readiness')
        port = profile.get_daemon_port()
        pid = profile.get_daemon_pid()
        if port is None or pid is None:
            raise AssertionError((port, pid))

        with socket.create_connection((Constants.LOCALHOST, port), timeout=2):
            pass

        identity_path = profile.paths.get_daemon_pid_file()
        identity = json.loads(identity_path.read_text(encoding='utf-8'))
        expected_installation = str(ProcessManager._installation_root())
        if identity['profile'] != profile_name:
            raise AssertionError(identity)
        if identity['installation_root'] != expected_installation:
            raise AssertionError(identity)
        if environment_root not in Path(expected_installation).resolve().parents:
            raise AssertionError(expected_installation)

        child = psutil.Process(pid)
        command = child.cmdline()
        if not command or Path(command[0]) != executable:
            raise AssertionError(command)
        if command[1:3] != ['-m', 'metor']:
            raise AssertionError(command)
        if profile_name not in command or '--locked' not in command:
            raise AssertionError(command)
        if (
            checkout in Path(child.cwd()).resolve().parents
            or Path(child.cwd()).resolve() == checkout
        ):
            raise AssertionError(f'child cwd remained in checkout: {child.cwd()}')

        print(
            'INSTALLED_MANAGED_SPAWN_OK',
            json.dumps(
                {
                    'executable': str(executable),
                    'installation_root': expected_installation,
                    'module': str(module_path),
                    'pid': pid,
                    'port': port,
                    'profile': profile_name,
                },
                sort_keys=True,
            ),
            flush=True,
        )
    finally:
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


def main() -> None:
    """Parses isolated acceptance paths and runs the installed spawn proof."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-parent', required=True, type=Path)
    parser.add_argument('--checkout', required=True, type=Path)
    args = parser.parse_args()
    run(args.data_parent, args.checkout)


if __name__ == '__main__':
    main()
