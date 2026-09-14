# GUI platform implementation decision

Status: vertical-slice validation in progress; no finished-platform claim.
Inputs: functional/layout v1.0. Integration gaps are tracked in
[GUI_INTEGRATION_MAP.md](GUI_INTEGRATION_MAP.md).

## Rendering and deployment

Use Kivy 2.3.1 with a small native Metor widget kit, SDL2 window/input/text,
OpenGL rendering, bundled Inter Tight upright 400/500/600/700, and local Lucide
symbols. No browser, webview, hosted asset service or runtime asset acquisition.
Kivy is MIT; Inter Tight is OFL; Lucide has ISC/Feather MIT notices.

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
Headset acoustics, complete duplex/unplug behavior, the canonical Windows
installer and physical appliance integration remain explicit gates.

## Resource and safety constraints

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
