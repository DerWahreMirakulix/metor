"""Accept built namespace wheels in isolated, non-editable consumer environments.

Run with a completed native release-bundle directory. No source path is added to
any consumer. All installs resolve offline from that directory's wheelhouses.
The invoking interpreter supplies build/typecheck tooling, not runtime imports.
"""

import argparse
import base64
import csv
import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv
from zipfile import ZipFile


GOOD_CONSUMER = """from typing import assert_type
from metor.client import MetorClient, FrontendHost, FrontendInteractions
from metor.core.api import Delivery, RuntimeSnapshotEvent
from metor.core.auth import derive_pin_verifier, build_session_auth_proof_from_key
from metor.versioning import APP_VERSION
client = MetorClient(1234)
assert_type(client.runtime_snapshot(), RuntimeSnapshotEvent | None)
assert_type(derive_pin_verifier("2468", "00" * 16), bytearray)
assert_type(build_session_auth_proof_from_key(bytes(32), "00" * 32), str)
assert_type(APP_VERSION, str)
def endpoint(host: FrontendHost, interactions: FrontendInteractions) -> int:
    return host.bootstrap(interactions).port
client.send_text("peer", Delivery.LIVE, "text", "id")
"""
BAD_CONSUMER = """from metor.client import MetorClient
from metor.core.api import Delivery
from metor.core.auth import derive_pin_verifier
client = MetorClient(object())
client.send_text("peer", "live", "text", "id")
derive_pin_verifier(42, "00" * 16)
"""
SDK_PROBE = """import os, sys
from pathlib import Path
from unittest.mock import patch
before = dict(os.environ)
with patch.object(Path, "home", side_effect=AssertionError("host lookup")):
    import metor.client, metor.core.api, metor.core.auth, metor.shared, metor.versioning
assert dict(os.environ) == before
assert "dotenv" not in sys.modules and "metor.data" not in sys.modules
assert "metor.core.daemon" not in sys.modules
from importlib.util import find_spec
assert find_spec("metor.data") is None and find_spec("metor.cli") is None
print("SDK_ONLY_INERT_OK", metor.client.__file__)
"""
FAKE_FRONTEND = """from metor.client import MetorClient
def launch(context):
    print("FAKE_STARTED_BEFORE_HOST")
    class Interaction:
        def confirm_daemon_start(self): raise AssertionError("unexpected prompt")
        def request_session_auth_secret(self): raise AssertionError("unexpected secret")
        def show_status(self, message): pass
    result = context.host.bootstrap(Interaction())
    assert type(result.port) is int and result.port > 0
    client = MetorClient(result.port, timeout=2)
    try:
        assert client.connect()
        assert client.bootstrap() is not None
        assert client.runtime_snapshot().profile == result.profile
        print("FAKE_DYNAMIC_IPC_OK")
    finally:
        client.disconnect()
    return 0
launch.contract_version = 2
"""
FAKE_HARNESS = """import atexit, tempfile, sys
from pathlib import Path
from unittest.mock import Mock, patch
from metor.utils import Constants
from metor.data import ProfileManager, ContactManager, HistoryManager, MessageManager
from metor.core.key import KeyManager
from metor.core.daemon.managed.engine import Daemon
from metor.cli.handlers import CommandHandlers
with tempfile.TemporaryDirectory() as root:
    Constants.DATA = Path(root) / ".metor"
    pm = ProfileManager("artifact")
    pm.initialize()
    tor = Mock()
    tor.onion = "a" * 56
    with patch("metor.core.daemon.managed.engine.daemon.signal.signal"):
        daemon = Daemon(pm, KeyManager(pm), tor, ContactManager(pm), HistoryManager(pm), MessageManager(pm))
    atexit.unregister(daemon.stop)
    try:
        daemon._ipc.start()
        assert pm.get_static_port() is None
        assert CommandHandlers.handle_chat(pm, frontend_id="closure-fake") == 0
        assert "metor.ui.terminal" not in sys.modules
    finally:
        daemon.stop()
"""

TERMINAL_HARNESS = FAKE_HARNESS.replace(
    'assert CommandHandlers.handle_chat(pm, frontend_id="closure-fake") == 0\n'
    '        assert "metor.ui.terminal" not in sys.modules',
    'with patch("metor.ui.terminal.chat.renderer.engine.InputHandler"), '
    'patch("metor.ui.terminal.chat.renderer.engine.Renderer.read_line", '
    'side_effect=["/help", "/clear", "/help", "/exit"]):\n'
    '            assert CommandHandlers.handle_chat(pm, frontend_id="terminal") == 0\n'
    '        print("TERMINAL_LOOP_HELP_REDRAW_OK")',
)


def audit_wheel_records(wheels: tuple[Path, ...]) -> None:
    """Checks real RECORD hashes, disjoint ownership and namespace marker placement."""
    selected = {
        path.name: path
        for path in wheels
        if path.name.startswith(('metor-', 'metor_sdk-', 'metor_ui_terminal-'))
    }
    if len(selected) != 3:
        raise RuntimeError('Expected exactly three coordinated Metor wheel names.')
    owned: dict[str, str] = {}
    contents: dict[str, bytes] = {}
    expected_markers = {
        'metor/client/py.typed',
        'metor/core/api/py.typed',
        'metor/core/auth/py.typed',
        'metor/shared/py.typed',
        'metor/versioning/py.typed',
    }
    for path in sorted(path for path in wheels if path.name in selected):
        with ZipFile(path) as archive:
            members = set(archive.namelist())
            record = next(
                name for name in members if name.endswith('.dist-info/RECORD')
            )
            rows = list(csv.reader(io.StringIO(archive.read(record).decode('utf-8'))))
            if {row[0] for row in rows} != members:
                raise RuntimeError(f'RECORD/member mismatch: {path.name}')
            for name, digest, size in rows:
                if name == record:
                    continue
                data = archive.read(name)
                actual = (
                    base64.urlsafe_b64encode(hashlib.sha256(data).digest())
                    .rstrip(b'=')
                    .decode()
                )
                if digest != 'sha256=' + actual or size != str(len(data)):
                    raise RuntimeError(f'Invalid RECORD hash/size: {name}')
            files = {name for name in members if name.startswith('metor/')}
            obsolete = {
                'metor/core/auth.py',
                'metor/versioning.py',
                'metor/utils/auth.py',
                'metor/utils/network.py',
            }
            if files & obsolete:
                raise RuntimeError('Wheel contains superseded implementation files.')
            if any(name in owned and owned[name] != path.name for name in files):
                raise RuntimeError('Overlapping installed namespace files.')
            for name in files:
                digest_bytes = hashlib.sha256(archive.read(name)).digest()
                if name in contents and contents[name] != digest_bytes:
                    raise RuntimeError(
                        'Bundle variants contain different runtime code.'
                    )
                owned[name] = path.name
                contents[name] = digest_bytes
            markers = {name for name in files if name.endswith('/py.typed')}
            if markers != (
                expected_markers if path.name.startswith('metor_sdk-') else set()
            ):
                raise RuntimeError(f'Incorrect typing-marker ownership: {path.name}')
        print(
            'WHEEL_RECORD_OWNERSHIP_OK',
            path.parent.parent.name,
            path.name,
            path.stat().st_size,
            hashlib.sha256(path.read_bytes()).hexdigest(),
            flush=True,
        )


def run_acceptance(bundle_root: Path) -> None:
    """Runs sequential install/uninstall and external positive/negative typing gates."""
    wheels = tuple(bundle_root.resolve().rglob('*.whl'))
    audit_wheel_records(wheels)
    wheel_dirs = sorted({str(path.parent) for path in wheels})
    if not wheel_dirs:
        raise ValueError('No built wheels supplied.')
    wheel_sources = ['--no-index']
    for directory in wheel_dirs:
        wheel_sources.extend(('--find-links', directory))
    environment = {
        k: v for k, v in os.environ.items() if k not in {'PYTHONPATH', 'MYPYPATH'}
    }
    with tempfile.TemporaryDirectory(prefix='metor-artifact-') as directory:
        root = Path(directory)
        venv.EnvBuilder(with_pip=True).create(root / 'consumer')
        executable = (
            root
            / 'consumer'
            / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        )

        def run(args: list[str], *, expected: int = 0) -> str:
            result = subprocess.run(
                args,
                cwd=root,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=180,
            )
            print(result.stdout, end='')
            if result.returncode != expected:
                raise RuntimeError(
                    f'Consumer command exited {result.returncode}, expected {expected}: {args[:4]}'
                )
            return result.stdout

        def install(name: str) -> None:
            run([str(executable), '-m', 'pip', 'install', *wheel_sources, name])
            run([str(executable), '-m', 'pip', 'check'])

        install('metor-sdk')
        run([str(executable), '-I', '-c', SDK_PROBE])
        good = root / 'good_consumer.py'
        bad = root / 'bad_consumer.py'
        config = root / 'mypy.ini'
        good.write_text(GOOD_CONSUMER, encoding='utf-8')
        bad.write_text(BAD_CONSUMER, encoding='utf-8')
        config.write_text('[mypy]\nstrict = True\n', encoding='utf-8')
        checker = [
            sys.executable,
            '-m',
            'mypy',
            '--config-file',
            str(config),
            '--no-incremental',
            '--python-executable',
            str(executable),
        ]
        run([*checker, str(good)])
        errors = run([*checker, str(bad)], expected=1)
        if errors.count('[arg-type]') != 3 or 'import-untyped' in errors:
            raise RuntimeError(
                'External SDK typing was missing or unexpectedly permissive.'
            )
        print('EXTERNAL_SDK_TYPING_POSITIVE_AND_NEGATIVE_OK')
        install('metor')
        for module, arguments in (
            ('metor', ['--help']),
            ('metor', ['--version']),
            ('metor.daemon_main', ['--help']),
            ('metor', ['chat', '--list-ui']),
        ):
            run([str(executable), '-I', '-m', module, *arguments])
        missing = run(
            [str(executable), '-I', '-m', 'metor', 'chat', '--ui', 'terminal'],
            expected=2,
        )
        if 'metor-ui-terminal' not in missing:
            raise RuntimeError('Missing frontend did not name its distribution.')

        # A separately built, non-shipped frontend exercises installed discovery,
        # base dispatch, deferred host and a dynamic real local daemon endpoint.
        fake = root / 'fake'
        fake.mkdir()
        (fake / 'closure_fake.py').write_text(FAKE_FRONTEND, encoding='utf-8')
        (fake / 'pyproject.toml').write_text(
            """[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"
[project]
name = "metor-closure-fake"
version = "0.0.0"
[project.entry-points."metor.ui_frontends"]
closure-fake = "closure_fake:launch"
[tool.setuptools]
py-modules = ["closure_fake"]
""",
            encoding='utf-8',
        )
        run(
            [
                sys.executable,
                '-m',
                'pip',
                'wheel',
                '--no-deps',
                '--no-build-isolation',
                str(fake),
                '-w',
                str(root),
            ]
        )
        run(
            [
                str(executable),
                '-m',
                'pip',
                'install',
                '--no-deps',
                str(next(root.glob('metor_closure_fake-*.whl'))),
            ]
        )
        output = run([str(executable), '-I', '-c', FAKE_HARNESS])
        if 'FAKE_DYNAMIC_IPC_OK' not in output:
            raise RuntimeError('Installed fake did not complete dynamic IPC.')
        run([str(executable), '-m', 'pip', 'uninstall', '-y', 'metor-closure-fake'])
        install('metor-ui-terminal')
        terminal_output = run([str(executable), '-I', '-c', TERMINAL_HARNESS])
        if (
            'TERMINAL_LOOP_HELP_REDRAW_OK' not in terminal_output
            or '/connect' not in terminal_output
        ):
            raise RuntimeError('Installed Terminal did not render its real chat help.')
        run(
            [
                str(executable),
                '-I',
                '-c',
                'from metor.client import load_frontend; from metor.ui.terminal import Help; assert load_frontend("terminal"); print("TERMINAL_ENTRY_AND_CHAT_HELP_OK")',
            ]
        )
        run([str(executable), '-m', 'pip', 'uninstall', '-y', 'metor-ui-terminal'])
        run([str(executable), '-I', '-m', 'metor', '--help'])
        run([str(executable), '-m', 'pip', 'check'])
        inventory = run([str(executable), '-I', '-m', 'metor', 'chat', '--list-ui'])
        if 'metor-ui-terminal' in inventory:
            raise RuntimeError('Uninstalled frontend remained in metadata inventory.')
        install('metor-ui-terminal')
        run(
            [
                str(executable),
                '-m',
                'pip',
                'uninstall',
                '-y',
                'metor-ui-terminal',
                'metor',
            ]
        )
        run([str(executable), '-I', '-c', SDK_PROBE])
        run([str(executable), '-m', 'pip', 'check'])
        print('ALL_ISOLATED_ARTIFACT_SCENARIOS_OK')


def main() -> None:
    """Parses the native built-bundle directory and executes artifact acceptance."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle_root', type=Path)
    run_acceptance(parser.parse_args().bundle_root)


if __name__ == '__main__':
    main()
