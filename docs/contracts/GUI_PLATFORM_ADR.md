# GUI platform implementation decision

Status: vertical-slice validation in progress; no finished-platform claim.
Inputs: functional/layout v1.0. Integration gaps are tracked in
[GUI_INTEGRATION_MAP.md](GUI_INTEGRATION_MAP.md).

Current verification (20 September): 673 regression tests, 46 minimum-size/150%
native SDL fixtures, fresh Linux and Windows bundles/consumers/installers and
installed desktop/simulator launch pass. Fresh Windows installed launch and
actual Razer capture/review also pass (30,720 bytes / 960 ms). On the RTX 4060 host, the
64-row synthetic input load from a local Windows installation measures 297 ms
first input and 71.8 ms subsequent p95; the WSL UNC installation measures about
1.26 seconds subsequent p95. Deployment location is part of the measurement.
Native screen-reader permutations, complete duplex/failure and physical adapter
acceptance remain separate open gates; see the dated acceptance report.

## Rendering and deployment

Use Kivy 2.3.1 with a small native Metor widget kit, SDL2 window/input/text,
OpenGL rendering, bundled Inter Tight upright 400/500/600/700, and local Lucide
symbols. No browser, webview, hosted asset service or runtime asset acquisition.
Kivy is MIT; Inter Tight is OFL; Lucide has ISC/Feather MIT notices.

Extra glyph coverage uses bundled DejaVu Sans 2.37 regular and actual bold,
including its redistribution notice. A packaged Inter Tight coverage map selects
the fallback for display labels and ordinary editors without caching user text.
Masked credentials retain a fixed font. Unsupported glyphs remain visible
replacement glyphs; no canonical character is deleted and complete Unicode
shaping/coverage is not claimed. Actual-font measurement uses the same selection
as rendering. The asset manifest and regression test pin every shipped asset.

Icon actions provide bounded pointer tooltips after a 600 ms hover dwell. Hints
use the existing accessible action name, do not activate or focus the target,
and are cancelled on departure, modal presentation, focus loss and privacy cover.
They draw inside the owning root canvas rather than an independent OS overlay.

Python 3.11 is the repository's native CI baseline. Linux x86-64 and Windows
x86-64 desktop are required targets; native execution evidence is separate per
host. ARM/Pi and physical GPIO/display/power configurations remain untested
until actual drivers and hardware are proved. An SDL desktop window alone is
not a physical appliance. Never register a pretend physical adapter.

Desktop defaults are 1180×760 logical units, minimum 360×640. At 960 wide,
use a 360 master and 1 divider. Device geometry is rotated before dividing by
scale; unsupported usable rectangles fail before driver/host activation.
Kivy density is applied once. Widgets measure wrapped text; screenshot scaling
cannot replace native text-scale or keyboard checks.

## Native accessibility ownership

The GUI-only `accessibility` package binds AccessKit 0.7.0 (MIT/Apache-2.0) to
Windows UI Automation and Linux AT-SPI. It owns a bounded immutable projection,
weak widget identities, a finite cross-thread action queue, native adapters and
presentation lifecycle binding. It does not change SDK/Core authorization or
store another message inventory. No compatibility axis changes are required.
See the [upstream adapter design](https://github.com/AccessKit/accesskit) and
[Python bindings](https://github.com/AccessKit/accesskit-python).

The `GuiState.covered` setter synchronously revokes native nodes, tooltip text
and pending assistive actions before returning. Covered Core presentation changes
also revoke the old native tree before deferred repaint; ordinary updates retain
control identities and focus. Only the foreground
root/modal and visible clipped controls are projected. Password fields expose
neither value nor count; ordinary fields support focus and bounded replacement.
PTT exposes focus but never a synthetic Click/hold. Actions execute on the GUI
thread after exact target, context, visibility and enabled-state checks.

Windows registration precedes the HWND's first visible frame. Kivy 2.3.1 queries
the active window's DPI during hidden initialization, so the bridge refreshes
its density using `GetDpiForWindow` for the actual owned HWND before constructing
controls. Native fixture entry points follow the same hidden-window sequence.
On exit, private projections are revoked immediately, but the Windows subclass
is released only after Kivy stops its subsequently installed input providers.
Removing it earlier lets those providers restore an already freed WndProc;
the installed launcher check exposed this ordering error and verifies the fix.
Linux registration requires a session D-Bus; no bus means unavailable native
accessibility, not simulated platform support.

Separate external OS clients verify labels, ordinary button invocation and
retained-element revocation before repaint on both systems. Windows additionally
verifies ordinary `ValuePattern.SetValue`; Linux verifies native editor focus.
The pinned AT-SPI adapter does not expose `EditableText.SetTextContents` in this
fixture; native focused keyboard editing remains the input path. These tests do
not certify every screen-reader product, reading/navigation permutation or
desktop environment. Linux probes must run with `GSETTINGS_BACKEND=memory`
**before** `dbus-run-session`, so activation uses only transient settings.

## Audio decision and acceptance limits

Use the public Voice byte-transfer boundary, which currently accepts a bounded
codec string without enforcing a codec/container. The candidate port uses
`pcm_s16le_16000_mono`: 16 kHz mono signed little-endian 16-bit PCM, 320 samples /
640 bytes per 20 ms capture frame. Every complete sample is an independent
decoder checkpoint; seeks round to bounded two-byte offsets without rereading
the recording. Incomplete samples are rejected. Other codec identifiers remain
unavailable, never heuristically decoded. Capture and playback run away from
the UI thread, with one output owner and simultaneous input permitted.
Sounddevice 0.5.3 / PortAudio is bound to GUI PTT through owner-safe staging and an explicitly confirmed headset route.
Linux requires system PortAudio; Windows wheels provide native support through
the upstream packaging. No microphone opens before explicit capture intent.
Headset routing is the initial candidate; speaker output cannot be labelled
AEC-capable without a tested echo canceller. Audio absence leaves text usable.
Native Windows capture/playback on the user-approved Razer BlackShark V2 HS
2.4 route passed a bounded duplex port probe. Native Windows installed SDL
startup also passed. The 2026-09-14 native GUI test additionally captured/reviewed 37,120 bytes
(1.16 seconds) using focused synthetic Space input, actual Razer I/O, the public
SDK and a temporary encrypted Core. No outbox message or audio export occurred.
Canonical Windows and Linux offline ZIP installers and both UI removal orders
passed on 15 September. Headset acoustics, complete duplex/unplug behavior and
physical appliance integration remain explicit gates. Current-source artifact
fingerprints are recorded in the acceptance report.

## Resource and safety constraints

The owner clarified the hardware boundary on 20 September: use
**frontend-independent, typed platform contracts**, with separate hardware
status, input and controlling-action interfaces. The canonical ownership
decision is in [ARCHITECTURE.md](../ARCHITECTURE.md#frontend-independent-typed-platform-contracts).
The SDK now owns `metor.client.platform`; active GUI capture/playback workers
consume its audio contracts. Physical button arbitration accepts its ordered
`ButtonSample` observations and cancels on sequence loss, duplicate delivery or
initially held controls. Status freshness and typed actuator outcomes are
separate from notifications. `PlatformBindings` now composes these independent
ports under one validated ID and is injected through `FrontendLaunchContext`.
Physical configuration must name that exact ID; no binding fails closed and
simulator rejects a binding. Optional action ports are activated only when their
own configuration tables select that ID; table omission disables the capability.
Cached battery status is read independently from input and actuation.

The GUI drains a bounded complete-sample queue on its UI thread. V21 requires an
explicit Power off action, finishes local capture/owner state, confirms
that the selected runtime is local and no other local profile is running,
confirms `PrepareProfileExit`, disconnects, and only then calls the fixed shutdown
port on a worker. The port still owns atomic deployment privilege and exclusive
runtime coordination. V22 retains continuous-chord/release arbitration, requests one exact
Core operation, and requires a restricted `device_lifecycle` grant when covered.
Shutdown is never requested from Initiated, EOF, key destruction, runtime release
or Safe alone. It requires combined Safe plus a terminal cleanup result, or the
five-second cleanup wait after Safe when transport/terminal reporting is lost.
If an already queued Safe milestone is installed after EOF, that prior EOF is
cleared as a terminal fact and the same five-second cleanup wait still applies.
The privileged port remains responsible for deployment-local authority and
exclusive runtime ownership. No board selection is required for this generic
integration; actual driver/OS shutdown and physical appliance evidence remain
separate gates.

The older unshipped `metor.ui.embedded.platform` prototype is historical and is
not the new public platform boundary. In particular, its combined battery/power
port and whole-blob audio model must not be used for the active GUI. Existing
historical regression fixtures are retained; active GUI callers migrate together
to the SDK surface, without compatibility aliases for the former GUI-local types.

Use functional section 20's finite queue/cache/draft budgets as named constants.
Workers return generation-tagged typed updates; no socket reader renders widgets.
Restriction covers all normal pixels immediately; purge never maps EOF to safety.
Simulator uses an isolated in-memory service and never receives a production
destruction or shutdown port. Device configuration is bounded strict TOML, with
registered IDs only, no arbitrary import, shell fragment or command template.

Native synthetic-render RSS is recorded beside comparison captures. Queue
occupancy and physical input latency remain unmeasured;
logical payload caps are not claims about Python/OpenGL process memory. Kivy
keyboard navigation and platform screen-reader exposure require separate
verification, including safe names under restriction.

Sources: [Kivy installation](https://kivy.org/doc/stable/gettingstarted/installation.html),
[Kivy window contract](https://kivy.org/doc/stable/api-kivy.core.window.html),
[sounddevice installation](https://python-sounddevice.readthedocs.io/en/0.5.3/installation.html).


The previous temporary embeddable Windows runtime was absent when validation
resumed. The replacement is the official CPython 3.11.9 NuGet runtime, which
includes `venv`, `ensurepip` and pip in the downloaded package. It remains under
an isolated temporary path and changes no system Python installation. All
repository-pinned GUI dependencies were installed successfully, and exact
Windows wheels were also collected for offline validation. Python documents
NuGet installations for build/CI use in its
[Windows deployment guide](https://docs.python.org/3.11/using/windows.html#the-nuget-org-packages).

### Final-source installed checkpoint, 15 September

Offline-installed desktop and simulator startup pass on Linux x86_64 and Windows
x86_64 with `python -I`, outside the checkout. The Windows installed GUI additionally
passes actual Razer capture and review through temporary encrypted Core data:
32,000 PCM bytes / 1,000 ms, no outbox publication or audio export. The test uses
synthetic focused Space input. Its module path resolves to the isolated virtual
environment's site-packages. Both platforms' nine bundled Metor wheels were
compared byte-for-byte against current source files, with zero mismatches.

The separate 20 MiB production-worker stress probe uses synthetic indexed SDK
ranges and counting output: 64 KiB maximum public read, 640-byte output frames,
16 MiB cache peak, 17,168,341-byte Python allocation peak and 48,504,832-byte
sampled RSS from a 31,162,368-byte baseline. Its sampled dispatch queue peak is
37 records. It completes in 23.226 seconds under tracemalloc. These are measured
Linux process values, not appliance limits or native audio acceptance.

The owner paused after further retained-root/badge changes. The installed
checkpoint above predates those changes; it is not final-source package proof
for the pause tree. Current tests, known latency observations and precise
continuation steps are in the acceptance report's 15 September pause handoff.
