# Metor GUI

This document owns the current GUI behavior, device configuration, and visual
rules. [FRONTENDS.md](FRONTENDS.md) owns the shared frontend boundary;
[ARCHITECTURE.md](../ARCHITECTURE.md) explains system decisions. The GUI uses
Core through the public SDK and typed IPC. It does not own authentication,
delivery, transport, persistence, or profile truth.

## Installation and startup

`metor-ui-gui` is the native Kivy frontend. Install it with compatible `metor`
and `metor-sdk` packages from the same release wheelhouse. The common launcher
selects a frontend using explicit `--ui`, then `METOR_UI`, then
`client.default_ui`, then Terminal. Installing the GUI does not select it by
default. A normal desktop start needs an SDL2/OpenGL display:

```sh
metor chat --ui gui
metor chat --ui gui --simulator
metor chat --ui gui --simulator --device-config docs/examples/gui-simulator.toml
```

The GUI opens its graphical shell before profile authentication, including when
started from a terminal. With no profiles it opens Create profile and says
`No profiles exist yet.` With several profiles and no valid default it opens the
picker. `-p NAME` is only an initial selection: a missing valid name stays in the
GUI for create/select recovery, and users may switch profiles later. A damaged
profile is shown as unavailable without treating the catalog as empty.

The GUI can open before profile authentication and presents authentication and
local daemon autostart choices graphically. Autostart follows the shared
`never`/`ask`/`always` policy; a remote endpoint never creates a substitute local
daemon. `--start-daemon` starts a missing local daemon upon profile activation;
`--no-start-daemon` leaves a missing daemon unavailable with a retry path. ASK
uses a graphical confirmation and passwords remain graphical, regardless of
terminal stdin. A daemon spawned by this chat invocation ends when the GUI closes
or switches away; an already running daemon is borrowed and survives. Optional
audio or camera failure leaves available text actions usable.

`--debug` adds bounded phase, timing and known-safe source locations to fatal
stderr output without printing untrusted exception text, class names or locals.
Fatal toolkit startup and unexpected event-loop termination return nonzero with a
safe stage summary even without debug. Normal first-run Close returns zero. A
caught worker exception keeps the graphical recovery status and prints a bounded
work phase, safe built-in category and GUI-source location only with `--debug`.
A missing display or native graphics dependency remains a platform prerequisite;
GUI setup does not switch to Terminal or start a simulator implicitly.
The repository has no registered production physical appliance adapter. A
simulator run demonstrates GUI behavior and cannot establish physical, acoustic,
or accessibility acceptance.

The installed GUI smoke runs
`python scripts/validate_installed_artifacts.py BUNDLE_ROOT --gui-smoke` with a
compatible window display. It starts the wheel-installed
common CLI and actual Kivy event loop against temporary data, checks the usable
Create profile and missing-selection picker views, closes through the native
Close handler, and verifies that an unexpected callback returns a safe nonzero
status. A generic X11 display such as Xvfb is suitable for this software gate;
the offscreen and simulator modes are not counted as a native window result.
The OS lifecycle notification source is replaced by an inert test adapter;
the real toolkit, app, frontend discovery and CLI still run. This smoke does
not exercise microphone, media, OS suspend, or physical devices.

## Device configuration (`device.toml`)

An explicit device file describes display, input, and locally available platform
capabilities. It is UTF-8 TOML, read only by the GUI, and does not hold profile
selection, credentials, contacts, messages, peer destinations, or GUI styling.
[gui-simulator.toml](../examples/gui-simulator.toml) is a working simulator
example. The Python `read_configuration` implementation is the executable
validator of this contract.

Pass a file with `--device-config PATH`, or set nonempty `METOR_DEVICE_CONFIG`;
the option wins. Relative paths resolve once against the invocation directory.
Metor does not search for an implicit file. Without a requested file, the GUI
uses built-in desktop defaults, or simulator defaults when `--simulator` is
explicit. A file never enables simulation by itself. An explicit missing,
unreadable, malformed, untrusted, or unsupported file fails before daemon
startup and driver activation; no desktop fallback occurs.

The supported top-level names are `schema_version`, `[display]`, `[input]`,
`[audio]`, `[camera]`, `[indicator]`, `[haptics]`, `[power]`, `[clipboard]`, and
`[drivers]`. `schema_version = 1`, `[display]`, and `[input]` are required.
Unknown fields and versions fail. The current parser accepts an empty
`[drivers]` table only; it does not load arbitrary driver names or commands.

| Table                                 | Current contract                                                                                                                                                                  |
| ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `[display]`                           | `adapter`, positive bounded native `width_px` and `height_px`; optional `rotation_deg` in 0/90/180/270 and finite `scale` from 0.25 through 8. `output` is currently unsupported. |
| `[input]`                             | `adapter`, exact `ptt_binding = "ptt"` and `power_binding = "power"`; optional boolean `touch`. PTT and Power have separate meanings.                                             |
| `[audio]`, `[camera]`                 | Optional `adapter = "none"` only in the current implementation; absence means unavailable.                                                                                        |
| `[indicator]`, `[haptics]`, `[power]` | Optional `adapter = "none"`, or the matching injected physical adapter ID when that port exists. Undeclared ports remain disabled.                                                |
| `[clipboard]`                         | Optional `policy = "disabled"` only.                                                                                                                                              |

`adapter` is a registered identity, not a Python import path. In simulator mode,
required display and input adapters are `simulator`, and physical
`PlatformBindings` are rejected. In physical mode, both required adapters must
match the injected `PlatformBindings.adapter_id`; without those bindings the
configuration fails. The optional physical ports must belong to that same
identity and be explicitly selected. Describing a port in TOML cannot create a
production driver or authorize Core actions. Simulator controls cannot call
production power or destruction paths.

Rotation transforms native dimensions before scale is applied. The resulting
usable display must be at least **360 × 640 logical units**. Desktop defaults
to 1180 × 760 logical units. A 480 × 800 native display at scale 1 and a
960 × 1600 display at scale 2 describe the same logical size. Unsupported
geometry fails instead of clipping essential controls.

The file is bounded to 64 KiB and must be a trusted regular file. The parser
does not follow symlinks or accept multiply linked files. On POSIX it requires
current-user ownership and rejects group or world write permission; Windows
uses native handle trust checks. Parsing uses strict types, field allowlists,
finite numeric bounds, and no evaluation of shell fragments, imports, or URLs.
Errors report a safe reason; configuration content and secrets must not enter
logs.

## Navigation and communication

The root is a DROP/LIVE communication overview, with access to Notifications,
Saved Contacts, and Settings. DROP and LIVE are distinct projections of the
same peer. Opening a view, changing a selector, Back, unlocking, or reattaching
does not connect, reconnect, accept, disconnect, change route, or fall back.
Those actions require explicit controls and typed Core commands. The GUI does
not infer online presence from a cached connection or change delivery semantics
because a view changed.

Core owns message IDs, peer identities, delivery, receipts, unread and pending
counts, recovery, fallback, and authorization. A local message identity includes
profile instance, peer, direction, and `msg_id`; aliases are mutable labels.
Pending LIVE-to-DROP fallback preserves `msg_id`. Resending an already
delivered own LIVE item creates a new DROP identity. A locally queued message,
remote delivery, and a read receipt are different facts. Unknown operation
outcomes are reconciled under the original identity before retry.

Text drafts are separate per peer and DROP/LIVE projection and survive
same-runtime navigation. They clear only after confirmed local acceptance;
rejection or unknown result retains the draft. Current GUI drafts are
disposable on GUI exit, restart, profile switch, hard lock, and purge. Core
pending or unseen content is never discarded because a GUI cache evicts it.
Peer-linked pins and preferences use the protected public profile boundary,
not a plaintext address or content side store.

## Contacts, notifications, and settings

Saved Contacts is the address book. Discovered peers appear in communication
views only while Core reports relevant state. Contact add, rename, removal,
and promotion use Core identity and results. Removing a saved contact can demote
its label without disconnecting active communication; old aliases must leave
notifications, accessibility nodes, and cached presentation. A QR scan is an
explicit camera action using the accepted contact format, bounded validation,
and the user's current intent. It cannot execute a URL or command, duplicate a
saved identity, or start a LIVE call without an explicit Start Live intent.
Address regeneration is a confirmed profile action and does not imply that old
contacts or conversations move automatically.

Notification Center entries are profile-scoped, bounded, and volatile. They
carry permitted kind, action reference, count, timestamp, and source identity,
never arbitrary remote details or message previews. Opening or clearing the
center does not mark messages read, delete history, accept calls, or reconnect.
Actionable state comes from Core and remains recoverable after an informational
entry is evicted. In restricted mode, Show all may show an authorized alias and
event kind, Anonymize shows only a non-identifying kind and permitted handle,
and Off suppresses unsolicited UI, badges, wake, and indicators. Anonymize is
the default. A post-unlock count is shown only if the GUI actually retained
privacy-permitted facts; it is never reconstructed from unread totals.

Settings present user concepts under Live, Privacy, Device, Profiles, and
Advanced. Core descriptors own types, limits, scope, effective values, and
policy. The GUI shows only supported controls and displays failed updates as
failures. Auto-play, locked LIVE continuation, locked-call acceptance, lock
notification privacy, application idle timeout, profile-name visibility,
keyboard layout, and pins are distinct preferences; changing one does not
silently grant another. Auto-play and locked LIVE continuation default Off;
manual locked-call acceptance defaults None. A profile password is the default
unlock method until a stronger explicit setup. Core-owned receipt, fallback,
history, resource, and contact policies retain their registry defaults. The GUI
does not add a second settings database or expose dangerous debug controls as
ordinary options. Activity history is Core metadata, separate from DROP
message history and the Notification Center.

## Voice and media

One PTT press has one input-source owner, bound profile, peer, delivery, GUI
generation, and logical message ID. Autorepeat, a second source, or a stale
release cannot create or retarget a recording. Losing the owning release,
focus, authorization, or device capability safely stops admission. Long I/O and
decode work stay off the UI thread; queues, caches, capture, and playback are
bounded and report overload rather than silently dropping accepted content.

DROP Voice enters an explicit review stage before commit or cancellation.
Uncommitted review drafts follow this GUI's disposable owner policy. LIVE Voice
uses the authorized current connection and keeps accepted data recoverable
under Core's owner-loss rules. Capture and playback may run concurrently where
the selected route supports them. A headset route is distinct from proven
speaker echo cancellation; unavailable routes are reported honestly. Playback
and range reads do not implicitly consume Voice. Release follows the public
safe handoff contract, and auto-play requires current foreground eligibility.
Scroll position and audio position are separate controls.

No microphone or camera starts on boot, navigation, reattach, or unlock.
Permissions are requested at explicit use. Missing optional media capability
disables dependent controls while text remains available.

## Privacy and lifecycle

Notifications contain no message body or Voice preview. Notification Center,
playback position, consumed LIVE presentation, and other GUI caches are bounded
volatile state. Application lock covers pixels, accessibility text, tooltips,
input, media, and indicators before private content can leak. A restricted
client is distinct from a hard-locked profile runtime; only an explicitly
authorized continued LIVE context may remain active. OS lock, suspend, and
resume keep the GUI covered until SDK/Core generation and authorization are
revalidated. Resume never reconstructs held PTT, starts capture, auto-plays,
or unlocks automatically.

Profile switch is a public lifecycle transaction: stop local producers,
preserve accepted Core work, clear old presentation, and attach the new profile
only after the old boundary is safe. A failed transition shows its actual phase
and never reuses credentials or revives old callbacks. Desktop window close
detaches this GUI; it does not power off the host, purge the profile, or end
other clients' LIVE activity. Physical Power and shutdown require configured
local bindings and confirmed safe Core preservation. The emergency Power+PTT
chord requires a prior Core lifecycle capability; hardware input never grants
authorization. Power-off after purge requires the documented combined safe
milestone, not request initiation, EOF, timeout, or keyslot removal alone.
Simulation cannot invoke production destruction or shutdown.

Peer text, aliases, and errors render as bounded plain content. The GUI makes
no automatic URL requests, rich previews, telemetry, or cloud font fetches.
Clipboard export is disabled by the current device configuration parser.
Volatile application state is not a promise against host swap, screenshots,
crash dumps, or physical media recovery.

## Lock and control semantics

Application Lock or short configured Power restricts this client while the
daemon and other authenticated clients may continue. It does not issue a Core
hard-lock command. Core validates PIN, password, cooldown, and locked-action
scope. A PIN cannot authenticate a cold or new client, and PIN-only access
cannot weaken profile credentials. Forgot PIN requests a password challenge.
An unconfirmed restriction stays covered and cannot create a second
unrestricted connection. Continued locked LIVE, when explicitly enabled, is
limited to the exact authorized foreground context generation; ending that
context revokes it even if the same peer calls again. Auto-accept from saved
contacts, manual locked-call acceptance, and auto-play are independent policies.

The software keyboard is local and offers QWERTY and QWERTZ without cloud
suggestions or a learned persistent dictionary. Desktop typing uses the
physical keyboard by default. Focus order follows visible reading order;
selection alone does not start communication. A focused PTT control may own
Space down/up, but text fields and global shortcuts cannot capture that press.
The text composer uses Enter for newline and Ctrl+Enter for explicit Send.
Incoming call UI does not steal an active typing or PTT owner. Modal focus
returns to a safe invoker; Escape/Back closes a reversible overlay before
navigating and cannot dismiss a privacy cover or accepted destructive work.

## Design and accessibility

The minimum usable client rectangle is **360 × 640 logical units**, excluding
window decoration and platform insets. Below 960 logical width, use one
foreground panel; from 960, a 360-unit master pane may stay beside the detail.
Crossing the breakpoint preserves route, selected IDs, focus, drafts, and
scroll anchor without a communication command. Controls must remain operable
at 1.5 text scale and with long content; wrap or grow rows and scroll forms
instead of shrinking text or hiding required actions. A keyboard inset must not
cover focused input or required actions.

DROP and LIVE require distinct labels as well as color. Status, disabled state,
focus, recording, errors, and destructive consequences cannot rely on color,
motion, or a physical LED alone. Accessible names and focus order follow
visible action meaning. Covers revoke private accessibility and tooltip text
before a lock or profile transition. The application uses packaged local
assets. Native rendering and accessibility claims require evidence on the
declared platform; simulator or offscreen rendering is not that evidence.

An unavailable physical adapter, audio route, microphone, camera, or display
has a truthful startup or capability error. Do not claim appliance support,
universal audio-device support, speaker echo cancellation, or screen-reader
certification from typed ports or simulator tests.

### Components and visual language

The root selector changes the master DROP/LIVE list. A selected peer owns the
foreground detail pane; root selection alone cannot promote a background peer
into a media owner. On a compact viewport, Back returns to the originating root
tab. In a wide viewport, Back clears the detail to a neutral conversation
prompt. Contacts, Notifications, and Settings replace the foreground detail,
while authentication, restriction, profile transition, and purge cover the whole
application. Incoming-call presentation cannot obscure or steal an existing
PTT owner. Confirmation and authentication sheets show the relevant current
identity and consequence; stale asynchronous results cannot close a newer
sheet or reveal an old profile.

Message rows grow with content. Own and incoming direction, DROP/LIVE delivery,
local acceptance, pending, delivered, read, and failed outcomes remain
visually distinct without relying on color alone. The text composer, recording
state, DROP Voice review, and playback controls are separate states. Timeline
scrolling and audio seeking have separate affordances. Status notices align
with the active content column and do not create extra communication actions.
Required controls stay visible or reachable at the minimum viewport and text
scale. Buttons and touch targets use at least 48 logical units where the
current component permits it; labels wrap or controls stack when necessary.

The packaged Inter Tight face is the visual baseline. The current core palette
uses background `#101619`, surface `#171F22`, primary text `#F3F7F6`, DROP
`#4ED7C8`, LIVE `#FFB454`, danger `#FF6474`, and success `#72D68C`.
Components may use related surface and outline tokens, but privacy, delivery,
and authorization meaning must stay legible in native rendering, with keyboard
focus and accessible names. Reduced motion preserves all state and safety cues.
