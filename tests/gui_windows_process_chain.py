"""Native Windows acceptance for installed GUI entry points and console windows.

Run only from an isolated wheel installation with an interactive desktop. The
harness creates disposable profile data, opens each real entry point, observes
its window, and closes it through the window manager.
"""

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import time

import psutil


WINDOW_READY_SECONDS = 40.0
WINDOW_EXIT_SECONDS = 20.0
FIXTURE_COMPILE_SECONDS = 30.0
FIXTURE_EXIT_SECONDS = 8.0
FIXTURE_WORKER_SECONDS = 20.0
PROFILE_SETUP_SECONDS = 40.0
PROFILE_START_SECONDS = 50.0
UIA_ACTION_SECONDS = 45.0
POLL_SECONDS = 0.1
WM_CLOSE = 0x0010

_UIA_CLICK = r"""
param([long]$Handle, [string]$ControlName, [string]$ExpectedName)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$Handle)
$buttonCondition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, $ControlName)
$expectedCondition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, $ExpectedName)
$clicked = $false
for ($attempt = 0; $attempt -lt 200; $attempt++) {
    $button = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $buttonCondition)
    if ($null -ne $button -and $button.Current.IsEnabled) {
        $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
        $clicked = $true
        break
    }
    Start-Sleep -Milliseconds 100
}
if (-not $clicked) { throw 'Expected GUI action was unavailable' }
for ($attempt = 0; $attempt -lt 200; $attempt++) {
    $expected = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $expectedCondition)
    if ($null -ne $expected -and $expected.Current.IsEnabled) {
        Write-Output 'NATIVE_GUI_ACTION_OK'
        exit 0
    }
    Start-Sleep -Milliseconds 100
}
throw 'Expected GUI state did not appear'
"""
NATIVE_PROFILE = 'windowed-autostart'


def _windows() -> list[tuple[int, int, str]]:
    """Read visible top-level windows in the current desktop session."""
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    found: list[tuple[int, int, str]] = []

    @callback_type
    def visit(hwnd: int, _extra: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, name, len(name))
        found.append((hwnd, owner.value, name.value))
        return True

    if not user32.EnumWindows(visit, 0):
        raise OSError('Could not enumerate native windows.')
    return found


def _console_windows() -> set[int]:
    """Identify consoles without disclosing their titles or process arguments."""
    return {hwnd for hwnd, _, name in _windows() if name == 'ConsoleWindowClass'}


def _environment(root: Path) -> dict[str, str]:
    """Give each installed entry point an isolated application data root."""
    environment = dict(os.environ)
    environment.pop('PYTHONPATH', None)
    environment.pop('METOR_DEVICE_CONFIG', None)
    environment.update(
        {
            'METOR_DATA_DIR_PARENT': str(root),
            'KIVY_HOME': str(root / 'kivy'),
            'KIVY_NO_ARGS': '1',
            'KIVY_NO_FILELOG': '1',
            'KIVY_NO_CONSOLELOG': '1',
            'KIVY_NO_CONFIG': '1',
        }
    )
    return environment


def _powershell() -> Path:
    """Resolve the operating system's PowerShell without searching PATH."""
    system_root = os.environ.get('SystemRoot')
    if not system_root:
        raise RuntimeError('Windows SystemRoot is unavailable for acceptance.')
    executable = (
        Path(system_root) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
    )
    if not executable.is_file():
        raise RuntimeError('Windows PowerShell 5.1 is unavailable for acceptance.')
    return executable


def _assert_original_console(hwnd: int) -> None:
    """Require the original test terminal to remain attached and visible."""
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    if kernel32.GetConsoleWindow() != hwnd or not user32.IsWindowVisible(hwnd):
        raise AssertionError('The original console was closed or hidden.')


def _post_close(hwnd: int) -> None:
    """Request closure through the actual native window message path."""
    user32 = ctypes.windll.user32
    user32.PostMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.PostMessageW.restype = wintypes.BOOL
    if not user32.PostMessageW(hwnd, WM_CLOSE, 0, 0):
        raise OSError('Could not request native window close.')


def _window_title(hwnd: int) -> str:
    """Read only the fixed native launcher dialog title."""
    user32 = ctypes.windll.user32
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    title = ctypes.create_unicode_buffer(64)
    user32.GetWindowTextW(hwnd, title, len(title))
    return title.value


def _watch_consoles(
    baseline: set[int],
    appeared: set[int],
    stopped: threading.Event,
    failed: threading.Event,
) -> None:
    """Catch short-lived extra consoles throughout one process-chain case."""
    while not stopped.wait(0.02):
        try:
            appeared.update(_console_windows() - baseline)
        except OSError:
            failed.set()
            return


def _wait_owned_window(
    process: subprocess.Popen[bytes], *, class_name: str | None = None
) -> int:
    """Wait for an exact process-owned native window with a bounded deadline."""
    deadline = time.monotonic() + WINDOW_READY_SECONDS
    while time.monotonic() < deadline:
        for hwnd, owner, name in _windows():
            if owner == process.pid and (
                name == class_name
                if class_name is not None
                else name != 'ConsoleWindowClass'
            ):
                return hwnd
        if process.poll() is not None:
            raise AssertionError(
                f'Installed GUI exited before its window: {process.returncode}'
            )
        time.sleep(POLL_SECONDS)
    raise AssertionError('Installed GUI did not open its native window.')


def _create_encrypted_profile(root: Path) -> None:
    """Create one temporary locked-start profile without a password in argv."""
    program = (
        'import sys\n'
        'from metor.application import initialize_runtime_environment\n'
        'from metor.data import ProfileManager, ProfileSecurityMode\n'
        'initialize_runtime_environment()\n'
        'password = sys.stdin.readline().rstrip("\\r\\n")\n'
        'result = ProfileManager.add_profile_folder('
        'sys.argv[1], security_mode=ProfileSecurityMode.ENCRYPTED, '
        'master_password=password)\n'
        'raise SystemExit(0 if result.success else 2)\n'
    )
    password = secrets.token_urlsafe(24)
    try:
        result = subprocess.run(
            [sys.executable, '-I', '-c', program, NATIVE_PROFILE],
            cwd=root,
            env=_environment(root),
            input=password + '\n',
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=PROFILE_SETUP_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AssertionError(
            'Temporary encrypted profile setup did not finish.'
        ) from exc
    if result.returncode != 0:
        raise AssertionError('Temporary encrypted profile setup failed.')


def _uia_action(hwnd: int, root: Path, control: str, expected: str) -> None:
    """Invoke one fixed visible AccessKit action from a separate OS client."""
    script = root / 'gui-accessibility-action.ps1'
    script.write_text(_UIA_CLICK, encoding='utf-8')
    try:
        result = subprocess.run(
            [
                str(_powershell()),
                '-NoProfile',
                '-NonInteractive',
                '-ExecutionPolicy',
                'Bypass',
                '-File',
                str(script),
                '-Handle',
                str(hwnd),
                '-ControlName',
                control,
                '-ExpectedName',
                expected,
            ],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=UIA_ACTION_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AssertionError('Native GUI accessibility action did not finish.') from exc
    if result.returncode != 0 or result.stdout.strip() != 'NATIVE_GUI_ACTION_OK':
        raise AssertionError('Native GUI accessibility action failed.')


def _is_locked_managed_daemon(process: psutil.Process) -> bool:
    """Recognize the fixed test profile's daemon command without exposing args."""
    args = process.cmdline()
    return (
        len(args) >= 10
        and args[1:4] == ['-I', '-m', 'metor']
        and args[4:6] == ['-p', NATIVE_PROFILE]
        and 'daemon' in args
        and '--frontend-managed' in args
        and '--locked' in args
        and process.is_running()
    )


def _managed_daemon_child(gui: subprocess.Popen[bytes]) -> psutil.Process | None:
    """Find only this GUI's locked automatic child, including its identity."""
    try:
        children = psutil.Process(gui.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        return None
    for child in children:
        try:
            if _is_locked_managed_daemon(child):
                if any(
                    descendant.name().lower() == 'tor.exe'
                    for descendant in child.children(recursive=True)
                ):
                    raise AssertionError(
                        'Locked GUI startup unexpectedly launched Tor.'
                    )
                return child
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def _managed_daemon_in_case(root: Path) -> psutil.Process | None:
    """Recover an orphan only from this disposable profile's unique cwd."""
    case_directory = os.path.normcase(os.path.abspath(root))
    for process in psutil.process_iter():
        try:
            if (
                _is_locked_managed_daemon(process)
                and os.path.normcase(os.path.abspath(process.cwd())) == case_directory
            ):
                return process
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    return None


def _wait_managed_daemon(gui: subprocess.Popen[bytes]) -> psutil.Process:
    """Wait for the real locked automatic child of this installed GUI."""
    deadline = time.monotonic() + PROFILE_START_SECONDS
    while time.monotonic() < deadline:
        if gui.poll() is not None:
            raise AssertionError('GUI exited before its automatic daemon started.')
        child = _managed_daemon_child(gui)
        if child is not None:
            return child
        time.sleep(POLL_SECONDS)
    raise AssertionError('Installed GUI did not start a locked automatic daemon.')


def _stop_verified_daemon(process: psutil.Process | None) -> None:
    """Reap only this case's verified temporary child after an abnormal exit."""
    if process is None:
        return
    try:
        if not process.is_running():
            return
        process.terminate()
        try:
            process.wait(timeout=WINDOW_EXIT_SECONDS)
        except psutil.TimeoutExpired:
            process.kill()
            process.wait(timeout=WINDOW_EXIT_SECONDS)
    except psutil.NoSuchProcess:
        pass


def _exercise_no_stream_failure(gui: Path, root: Path, original_console: int) -> None:
    """Require the installed graphical launcher to report a bounded startup error."""
    baseline = _console_windows()
    appeared: set[int] = set()
    stopped = threading.Event()
    failed = threading.Event()
    observer = threading.Thread(
        target=_watch_consoles, args=(baseline, appeared, stopped, failed), daemon=True
    )
    observer.start()
    # A GUI-subsystem launcher has no Python standard streams. An invalid
    # deployment path fails before Kivy and must surface the fixed native dialog.
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            [str(gui), '--device-config', str(root / 'missing-device.toml')],
            cwd=root,
            env=_environment(root),
            close_fds=True,
        )
        dialog = _wait_owned_window(process, class_name='#32770')
        if _window_title(dialog) != 'Metor GUI':
            raise AssertionError('Installed GUI opened an unexpected native dialog.')
        _assert_original_console(original_console)
        _post_close(dialog)
        try:
            status = process.wait(timeout=WINDOW_EXIT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise AssertionError('Installed GUI error dialog did not close.') from exc
        if status != 2:
            raise AssertionError(
                f'Installed GUI startup error returned unexpected status {status}.'
            )
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=WINDOW_EXIT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=WINDOW_EXIT_SECONDS)
        stopped.set()
        observer.join(timeout=2)
    _assert_original_console(original_console)
    if failed.is_set() or observer.is_alive():
        raise AssertionError('Native console observation failed.')
    if appeared or _console_windows() - baseline:
        raise AssertionError('Installed GUI startup error opened another console.')


def _exercise_windowed_autostart(gui: Path, root: Path, original_console: int) -> None:
    """Follow a real installed GUI and its locked automatic daemon to shutdown."""
    _create_encrypted_profile(root)
    baseline = _console_windows()
    appeared: set[int] = set()
    stopped = threading.Event()
    failed = threading.Event()
    observer = threading.Thread(
        target=_watch_consoles, args=(baseline, appeared, stopped, failed), daemon=True
    )
    observer.start()
    process: subprocess.Popen[bytes] | None = None
    daemon: psutil.Process | None = None
    try:
        process = subprocess.Popen(
            [str(gui), '-p', NATIVE_PROFILE, '--start-daemon'],
            cwd=root,
            env=_environment(root),
            close_fds=True,
        )
        window = _wait_owned_window(process)
        _uia_action(window, root, 'Open profile', 'Profile password')
        daemon = _wait_managed_daemon(process)
        _assert_original_console(original_console)
        _uia_action(window, root, 'Cancel', 'Switch profile')
        _post_close(window)
        try:
            status = process.wait(timeout=WINDOW_EXIT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise AssertionError('Installed GUI did not close after cancel.') from exc
        if status != 0:
            raise AssertionError(f'Installed GUI exited with status {status}.')
        try:
            daemon_status = daemon.wait(timeout=WINDOW_EXIT_SECONDS)
        except psutil.TimeoutExpired as exc:
            raise AssertionError(
                'Automatic daemon outlived its final installed GUI.'
            ) from exc
        if daemon_status != 0:
            raise AssertionError(
                f'Automatic daemon exited with status {daemon_status}.'
            )
    finally:
        if daemon is None and process is not None and process.poll() is None:
            # A failed UIA action can occur after bootstrap. Capture the exact
            # child before losing its parent relationship during GUI cleanup.
            daemon = _managed_daemon_child(process)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=WINDOW_EXIT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=WINDOW_EXIT_SECONDS)
        if daemon is None:
            # A crashed GUI can reparent its already started daemon. The
            # disposable cwd and fixed argv keep this cleanup case-specific.
            daemon = _managed_daemon_in_case(root)
        _stop_verified_daemon(daemon)
        stopped.set()
        observer.join(timeout=2)
    _assert_original_console(original_console)
    if failed.is_set() or observer.is_alive():
        raise AssertionError('Native console observation failed.')
    if appeared or _console_windows() - baseline:
        raise AssertionError('Installed GUI automatic daemon opened another console.')


def _exercise(command: list[str], root: Path) -> None:
    """Require one visible GUI, no new console, and a bounded normal close."""
    baseline = _console_windows()
    environment = _environment(root)
    process = subprocess.Popen(
        command,
        cwd=root,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + WINDOW_READY_SECONDS
        gui_window: int | None = None
        while time.monotonic() < deadline:
            if _console_windows() - baseline:
                raise AssertionError('An additional Windows console appeared.')
            for hwnd, owner, name in _windows():
                if owner == process.pid and name != 'ConsoleWindowClass':
                    gui_window = hwnd
                    break
            if gui_window is not None:
                break
            if process.poll() is not None:
                raise AssertionError(
                    f'GUI exited before its window: {process.returncode}'
                )
            time.sleep(POLL_SECONDS)
        if gui_window is None:
            raise AssertionError('Installed GUI did not open a native window.')
        user32 = ctypes.windll.user32
        user32.PostMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.PostMessageW.restype = wintypes.BOOL
        if not user32.PostMessageW(gui_window, WM_CLOSE, 0, 0):
            raise OSError('Could not request GUI close.')
        try:
            status = process.wait(timeout=WINDOW_EXIT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise AssertionError(
                'GUI did not close in the acceptance deadline.'
            ) from exc
        if status != 0:
            raise AssertionError(f'GUI exited with status {status}.')
        if _console_windows() - baseline:
            raise AssertionError('An additional Windows console remained after close.')
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=WINDOW_EXIT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=WINDOW_EXIT_SECONDS)


def _exercise_quick_unlock(root: Path) -> None:
    """Observe the installed ACL helper while it protects disposable data."""
    from metor.core.daemon.managed.quick_unlock import (
        PIN_SALT_BYTES,
        PIN_VERIFIER_BYTES,
        QuickUnlockStore,
    )

    baseline = _console_windows()
    appeared: set[int] = set()
    stopped = threading.Event()
    observation_failed = threading.Event()

    def observe() -> None:
        """Record a short-lived helper console during the blocking ACL call."""
        while not stopped.wait(0.05):
            try:
                appeared.update(_console_windows() - baseline)
            except OSError:
                observation_failed.set()
                return

    observer = threading.Thread(target=observe, daemon=True)
    observer.start()
    try:
        store = QuickUnlockStore(root / 'quick-unlock' / 'verifier.json')
        store.configure('00' * PIN_SALT_BYTES, '11' * PIN_VERIFIER_BYTES)
        assert store.metadata() is not None
        store.remove()
    finally:
        stopped.set()
        observer.join(timeout=2)
    if observation_failed.is_set():
        raise AssertionError('Native console observation failed.')
    if appeared or _console_windows() - baseline:
        raise AssertionError('Quick-unlock ACL helper opened another console.')


def _console_fixture(root: Path) -> Path:
    """Compile a fixed, disposable native console child with Windows PowerShell."""
    system_root = os.environ.get('SystemRoot')
    if not system_root:
        raise RuntimeError('Windows SystemRoot is unavailable for fixture compilation.')
    powershell = (
        Path(system_root) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
    )
    if not powershell.is_file():
        raise RuntimeError(
            'Windows PowerShell 5.1 is unavailable for the console fixture.'
        )
    source = root / 'tor-console-fixture.cs'
    script = root / 'compile-console-fixture.ps1'
    executable = root / 'tor-console-fixture.exe'
    source.write_text(
        'using System;\n'
        'using System.Threading;\n'
        'public static class TorConsoleFixture {\n'
        '  public static int Main(string[] args) {\n'
        '    string config = Console.In.ReadToEnd();\n'
        '    if (args.Length != 4 || args[0] != "-f" || args[1] != "-" ||\n'
        '        args[2] != "__OwningControllerProcess" ||\n'
        '        !config.Contains("Log NOTICE stdout")) return 2;\n'
        '    Console.WriteLine("Bootstrapped 100%");\n'
        '    Console.Out.Flush();\n'
        '    Thread.Sleep(3000);\n'
        '    return 0;\n'
        '  }\n'
        '}\n',
        encoding='ascii',
    )
    script.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        'Add-Type -LiteralPath $args[0] -OutputAssembly $args[1] '
        '-OutputType ConsoleApplication\n',
        encoding='ascii',
    )
    try:
        result = subprocess.run(
            [
                str(powershell),
                '-NoProfile',
                '-NonInteractive',
                '-ExecutionPolicy',
                'Bypass',
                '-File',
                str(script),
                str(source),
                str(executable),
            ],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=FIXTURE_COMPILE_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError('Windows console fixture compiler did not run.') from exc
    if result.returncode != 0 or not executable.is_file():
        raise RuntimeError(
            f'Windows console fixture compilation failed ({result.returncode}).'
        )
    binary = executable.read_bytes()
    if len(binary) < 128:
        raise AssertionError('Console fixture is not a valid PE executable.')
    pe_offset = int.from_bytes(binary[0x3C:0x40], 'little')
    if binary[pe_offset : pe_offset + 4] != b'PE\x00\x00':
        raise AssertionError('Console fixture lacks a PE header.')
    subsystem = int.from_bytes(binary[pe_offset + 92 : pe_offset + 94], 'little')
    if subsystem != 3:
        raise AssertionError('Console fixture is not a console executable.')
    return executable


def _tor_child_worker(executable: Path, root: Path) -> int:
    """Spawn the fixture from a process with no inherited Windows console."""
    from metor.core.tor_windows import launch_tor_without_console

    if ctypes.windll.kernel32.GetConsoleWindow() != 0:
        return 2
    config = {
        'SocksPort': '10241',
        'ControlPort': '10242',
        'CookieAuthentication': '1',
        'DataDirectory': str(root / 'tor-data'),
        'HiddenServiceDir': str(root / 'hidden-service'),
        'HiddenServicePort': '80 127.0.0.1:10243',
    }
    process: subprocess.Popen[bytes] | None = None
    try:
        process = launch_tor_without_console(tor_cmd=str(executable), config=config)
        try:
            return 0 if process.wait(timeout=FIXTURE_EXIT_SECONDS) == 0 else 4
        except subprocess.TimeoutExpired:
            return 5
    except OSError:
        return 3
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=WINDOW_EXIT_SECONDS)


def _exercise_tor_child(root: Path) -> None:
    """Observe the installed Tor creation path with a real console executable."""
    executable = _console_fixture(root)
    baseline = _console_windows()
    appeared: set[int] = set()
    stopped = threading.Event()
    observation_failed = threading.Event()

    def observe() -> None:
        """Catch transient and persistent child consoles during bootstrap."""
        while not stopped.wait(0.02):
            try:
                appeared.update(_console_windows() - baseline)
            except OSError:
                observation_failed.set()
                return

    observer = threading.Thread(target=observe, daemon=True)
    worker: subprocess.Popen[bytes] | None = None
    observer.start()
    try:
        worker = subprocess.Popen(
            [
                sys.executable,
                '-I',
                str(Path(__file__).resolve()),
                '--tor-child-worker',
                str(executable),
                str(root),
            ],
            cwd=root,
            env=_environment(root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            status = worker.wait(timeout=FIXTURE_WORKER_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise AssertionError('Tor child worker exceeded its deadline.') from exc
        if status != 0:
            raise AssertionError(f'Tor child worker failed with status {status}.')
    finally:
        if worker is not None and worker.poll() is None:
            worker.kill()
            worker.wait(timeout=WINDOW_EXIT_SECONDS)
        stopped.set()
        observer.join(timeout=2)
    if observation_failed.is_set():
        raise AssertionError('Native Tor child console observation failed.')
    if appeared or _console_windows() - baseline:
        raise AssertionError('Tor child opened another Windows console.')


def main() -> None:
    """Exercise both real installed launchers with temporary profile state."""
    if os.name != 'nt':
        raise RuntimeError('Native Windows acceptance requires Windows.')
    if len(sys.argv) == 4 and sys.argv[1] == '--tor-child-worker':
        raise SystemExit(_tor_child_worker(Path(sys.argv[2]), Path(sys.argv[3])))
    if len(sys.argv) != 1:
        raise RuntimeError('Unexpected Windows acceptance arguments.')
    scripts = Path(sys.executable).parent
    cli = scripts / 'metor.exe'
    gui = scripts / 'metor-gui.exe'
    if not cli.is_file() or not gui.is_file():
        raise RuntimeError('The isolated installation lacks a GUI or CLI entry point.')
    kernel32 = ctypes.windll.kernel32
    kernel32.GetConsoleWindow.restype = wintypes.HWND
    kernel32.AllocConsole.restype = wintypes.BOOL
    if kernel32.GetConsoleWindow() == 0:
        if not kernel32.AllocConsole():
            raise RuntimeError('Could not establish the original test console.')
    original_console = int(kernel32.GetConsoleWindow())
    _assert_original_console(original_console)
    with tempfile.TemporaryDirectory(prefix='metor-win-gui-') as directory:
        root = Path(directory)
        for name, command in (
            ('cli', [str(cli), 'chat', '--ui', 'gui']),
            ('gui', [str(gui)]),
        ):
            case_root = root / name
            case_root.mkdir()
            _exercise(command, case_root)
            _assert_original_console(original_console)
        no_stream_root = root / 'no-stream-error'
        no_stream_root.mkdir()
        _exercise_no_stream_failure(gui, no_stream_root, original_console)
        autostart_root = root / 'windowed-autostart'
        autostart_root.mkdir()
        _exercise_windowed_autostart(gui, autostart_root, original_console)
        _exercise_quick_unlock(root)
        _exercise_tor_child(root)
    _assert_original_console(original_console)
    print('WINDOWS_INSTALLED_GUI_ENTRYPOINTS_OK')


if __name__ == '__main__':
    main()
