"""Native UIA/AT-SPI privacy and action probe against an isolated synthetic window."""

# ruff: noqa: E402

import os
import faulthandler
from pathlib import Path
import subprocess
import tempfile
import sys
import threading

os.environ['KIVY_NO_ARGS'] = '1'
os.environ['KIVY_NO_FILELOG'] = '1'
os.environ['KIVY_NO_CONFIG'] = '1'
os.environ['KCFG_GRAPHICS_WINDOW_STATE'] = 'hidden'

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout

from metor.ui.gui.accessibility import AccessibilityBridge
from metor.ui.gui.state import GuiState
from metor.ui.gui.widgets import Action, Label, SecretInput, TextField


SCRIPT = r"""
param([long]$Handle, [string]$Folder)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$Handle)
$condition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, 'Fixture private alias')
$old = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condition)
if ($null -eq $old) {
    $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition) | ForEach-Object { Write-Output $_.Current.Name }
    throw 'Private label absent from native UIA tree'
}
$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
foreach ($item in $all) {
    if ($item.Current.Name.Contains('fixture-secret')) { throw 'Secret exposed as name' }
    $value = $null
    if ($item.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$value)) {
        if ($value.Current.Value.Contains('fixture-secret')) { throw 'Secret exposed as value' }
        if ($item.Current.IsPassword -and $value.Current.Value.Length -ne 0) { throw 'Password length exposed through ValuePattern' }
    }
    $text = $null
    if ($item.Current.IsPassword -and $item.TryGetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern, [ref]$text)) {
        if ($text.DocumentRange.GetText(-1).Length -ne 0) { throw 'Password content or length exposed through TextPattern' }
    }
}
$actionCondition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, 'Fixture action')
$button = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $actionCondition)
$invoke = $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
$invoke.Invoke()
for ($attempt = 0; $attempt -lt 100; $attempt++) {
    if (Test-Path (Join-Path $Folder 'invoked')) { break }
    Start-Sleep -Milliseconds 100
}
if (!(Test-Path (Join-Path $Folder 'invoked'))) { throw 'Native invocation did not reach the current control' }
$editorCondition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, 'Fixture editor')
$editor = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $editorCondition)
$editor.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue('Fixture changed')
for ($attempt = 0; $attempt -lt 100; $attempt++) {
    if (Test-Path (Join-Path $Folder 'edited')) { break }
    Start-Sleep -Milliseconds 100
}
if (!(Test-Path (Join-Path $Folder 'edited'))) { throw 'Native edit did not reach the current field' }
[IO.File]::WriteAllText((Join-Path $Folder 'before'), 'read')
for ($attempt = 0; $attempt -lt 100; $attempt++) {
    if (Test-Path (Join-Path $Folder 'covered')) { break }
    Start-Sleep -Milliseconds 100
}
if (!(Test-Path (Join-Path $Folder 'covered'))) { throw 'Cover timeout' }
if ($null -ne $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condition)) { throw 'Private native node survived cover' }
$stale = $false
try { $stale = $old.Current.Name -eq 'Fixture private alias' } catch {}
if ($stale) { throw 'Retained native element exposes private alias' }
Write-Output 'NATIVE_UIA_PRIVACY_OK'
"""


class Probe(App):
    """Runs a separate OS accessibility client while the native GUI loop stays live."""

    def __init__(self, folder: Path) -> None:
        """Owns fixture files and the bounded external test process.

        Args:
            folder: Temporary test-only synchronization directory.
        Returns:
            None
        """
        super().__init__()
        self.folder = folder
        self.state = GuiState()
        self.state.covered = False
        self.bridge: AccessibilityBridge | None = None
        self.process: subprocess.Popen[str] | None = None
        self.passed = False

    def build(self) -> BoxLayout:
        """Creates only synthetic presentation, with no profile or Core process.

        Args:
            None
        Returns:
            BoxLayout: Native fixture root.
        """
        self.bridge = AccessibilityBridge(self.state, lambda: None)
        root = BoxLayout(orientation='vertical')
        root.add_widget(Label('Fixture private alias'))
        root.add_widget(SecretInput(text='fixture-secret'))
        editor = TextField(hint_text='Fixture editor', text='Fixture initial')
        editor.bind(
            text=lambda _widget, value: (
                (self.folder / 'edited').write_text('edited', encoding='utf-8')
                if value == 'Fixture changed'
                else None
            )
        )
        editor.bind(
            focus=lambda _widget, value: (
                (self.folder / 'focused').write_text('focused', encoding='utf-8')
                if value
                else None
            )
        )
        root.add_widget(editor)
        root.add_widget(
            Action(
                'Fixture action',
                lambda: (self.folder / 'invoked').write_text(
                    'invoked', encoding='utf-8'
                ),
            )
        )
        Clock.schedule_once(self.start, 1)
        Clock.schedule_once(lambda _dt: self.stop(), 60)
        return root

    def start(self, _elapsed: float) -> None:
        """Starts an external UIA query without blocking native callback dispatch.

        Args:
            _elapsed: Native layout delay.
        Returns:
            None
        """
        assert self.bridge is not None and self.root is not None
        self.bridge.rendered(self.root)
        script = self.folder / 'query.ps1'
        script.write_text(SCRIPT, encoding='utf-8')
        command = [
            'powershell.exe',
            '-NoProfile',
            '-ExecutionPolicy',
            'Bypass',
            '-File',
            str(script),
            '-Handle',
            str(Window.get_window_info().window) if os.name == 'nt' else '0',
            '-Folder',
            str(self.folder),
        ]
        if os.name != 'nt':
            command = [
                '/usr/bin/python3',
                str(Path(__file__).with_name('gui_atspi_client.py')),
                str(self.folder),
            ]
        threading.Thread(target=self._launch, args=(command,), daemon=True).start()
        Clock.schedule_interval(self.poll, 0.1)

    def _launch(self, command: list[str]) -> None:
        """Keeps process creation outside the thread serving native window messages.

        Args:
            command: Exact test-only UIA client invocation.
        Returns:
            None
        """
        self.process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=self.folder,
        )

    def poll(self, _elapsed: float) -> None:
        """Revokes before repaint and verifies the retained external native element.

        Args:
            _elapsed: Fixture polling interval.
        Returns:
            None
        """
        assert self.bridge is not None
        if self.process is None:
            return
        self.bridge.poll()
        if (self.folder / 'before').exists() and not self.state.covered:
            self.state.covered = True
            assert not self.bridge.model.read().nodes
            # Deliberately do not repaint: the synchronous native privacy fence is under test.
            (self.folder / 'covered').write_text('covered', encoding='utf-8')
        if self.process.poll() is not None:
            output, error = self.process.communicate()
            print(output, error)
            self.passed = self.process.returncode == 0 and (
                'NATIVE_UIA_PRIVACY_OK' in output or 'NATIVE_ATSPI_PRIVACY_OK' in output
            )
            self.stop()

    def on_stop(self) -> None:
        """Closes native registrations and any timed-out fixture subprocess.

        Args:
            None
        Returns:
            None
        """
        if self.process is not None and self.process.poll() is None:
            self.process.kill()
            self.process.communicate()
        if self.bridge is not None:
            self.bridge.close()


if __name__ == '__main__':
    faulthandler.dump_traceback_later(15, repeat=True, file=sys.__stderr__)
    with tempfile.TemporaryDirectory(prefix='metor-uia-') as directory:
        app = Probe(Path(directory))
        app.run()
        if not app.passed:
            raise SystemExit('Native accessibility validation failed')
