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

On Windows, launch the installed `metor-gui.exe` from the environment's
`Scripts` directory for a graphical start without a console window. The
release GUI bundle places it in `.venv\Scripts`. `metor chat --ui gui` remains
available from PowerShell for diagnostics; that original terminal remains open.
Neither start path creates a console for GUI child processes (daemon, Tor or the
Windows ACL helper). A failure before the graphical shell
opens produces a generic Windows dialog that points to that diagnostic command.

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
terminal stdin. GUI and Terminal sessions share an automatically started daemon;
it exits after the last participating frontend releases it. A second GUI or
Terminal session may continue on that daemon even when the original GUI closes
or changes profile. An independently started daemon survives every frontend
exit. Optional
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
Create profile and missing-selection picker views, opens a disposable encrypted
profile with `--start-daemon` until the password prompt is visible, closes
through the native Close handler, and verifies that an unexpected callback
returns a safe nonzero status. The profile stays locked, so this deterministic
gate does not connect to public Tor. A generic X11 display such as Xvfb is
suitable for this software gate;
the offscreen and simulator modes are not counted as a native window result.
The OS lifecycle notification source is replaced by an inert test adapter;
the real toolkit, app, frontend discovery and CLI still run. This smoke does
not exercise microphone, media, OS suspend, or physical devices.

The locked-call layout fixture
`python tests/gui_native_locked_call.py --result RESULT.json --images IMAGE_DIR`
checks concrete Kivy widgets at 360×640 with 1.5× text scaling. Synthetic public
Call DTOs and pointer input exercise mute, hangup and the scrollable unlock form
for PIN, password and no-local-secret methods, including the touch keyboard.
Its result records that Core and physical audio hardware are absent; it proves
layout and hit targets rather than call transport or acoustic continuation.

The conversation fixture
`python tests/gui_native_conversation.py --result RESULT.json` checks actual
Kivy frame geometry and synthetic pointer/keyboard interactions at 360×640 with
1.5× text scaling; `--width 1180 --height 760` covers the wide layout. It checks
first-frame message placement, feedback expiry and focus revocation, repeated
Send, Enter/Shift+Enter, header actions, closed audio dialogs and Back navigation.
`python tests/gui_native_text_input.py --result RESULT.json` also exercises the
local keyboard and preserves credential-field behavior. These fixtures use
injected SDK results and no Core or audio streams. An offscreen SDL run proves
these widget interactions only; it does not replace the installed native-window
smoke, physical input, or acoustic acceptance.

The Core-backed conversation fixture runs the actual `MetorApp`, controller and
SDK against two disposable encrypted Core runtimes. X11 XTest mouse and keyboard
events enter through SDL; GUI commands, request results and runtime callbacks
are not replaced. It checks authenticated startup, contact changes, repeated
DROP sending before LIVE, history, focus, navigation and LIVE delivery. First-draw
probes check immediate connection feedback before Core acknowledgment, retained
DROP content on tab changes and measured header alignment. Real peer rejection
and an unreachable test route exercise actionable connection failures and retry.
An outgoing Cancel is held before qualified Core execution to check disabled
`Cancelling Live…` on its first draw and suppression of repeated clicks. Settings →
Profiles → My contact opens with one native click; Back returns through the
same hierarchy. At desktop size, DROP/LIVE switching keeps Settings open and
one sidebar conversation click opens its detail.
An actual Terminal subprocess exchanges text with the GUI through the same Core
peer path; send failures retain the draft with a local explanation:

```sh
python tests/gui_native_core.py --width 360 --height 640 --font-scale 1.5 \
  --revision COMMIT_OR_TREE --result gui-core.json --images gui-core-images
```

Run with an explicit virtual X11 display and the SDL2 window provider; use
`--width 1180 --height 760` for the desktop layout. `--mode installed` requires
a fresh wheel-installed interpreter outside the checkout and rejects GUI source
imports. Results record the loaded source, revision, input events and observed
timings. The fixture replaces Tor process/SOCKS routing with local TCP while
retaining peer signatures, framing, persistence and delivery workers. Its OS
lifecycle source is inert. It opens no audio stream and does not establish
physical input, native lock/suspend handling, acoustic support or public Tor
connectivity.

On Windows, add `--windows-launch` to check both installed entry-point
executables, the graphical launcher without standard streams, the temporary
locked `--start-daemon` path through native UI Automation, the original
terminal, and console windows created by daemon and synthetic Tor children.
This acceptance runs on a native Windows desktop, not WSL.

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

The supported top-level names are `schema_version`, `[platform]`, `[display]`, `[input]`,
`[audio]`, `[camera]`, `[indicator]`, `[haptics]`, `[power]`, `[clipboard]`, and
`[drivers]`. `schema_version = 1`, `[display]`, and `[input]` are required.
Unknown fields and versions fail. The current parser accepts an empty
`[drivers]` table only; it does not load arbitrary driver names or commands.
`[platform]` selects an installed adapter by stable ID; `[platform.config]`
holds at most 32 bounded scalar values and passes only to that adapter's
preactivation validator. Existing version 1 files without `[platform]` retain
their `[display].adapter` identity. A selected adapter's concrete fields are
specified by its installed package, never inferred by the GUI. The generic
boundary accepts finite numbers with absolute value at most 10¹²; this keeps
deployment data small before provider validation. Each provider then applies
its own narrower field ranges.

| Table                                 | Current contract                                                                                                                                                                                                                            |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `[platform]`                          | Optional `adapter` and bounded `[platform.config]` for a physical adapter. Simulation has no platform provider.                                                                                                                             |
| `[display]`                           | `adapter`, positive bounded native `width_px` and `height_px`; optional `rotation_deg` in 0/90/180/270 and finite `scale` from 0.25 through 8. `output` is currently unsupported.                                                           |
| `[input]`                             | `adapter`, exact `ptt_binding = "ptt"` and `power_binding = "power"`; optional boolean `touch`. PTT and Power have separate meanings.                                                                                                       |
| `[audio]`, `[camera]`                 | Optional `adapter = "none"` only in the current implementation; absence means unavailable.                                                                                                                                                  |
| `[indicator]`, `[haptics]`, `[power]` | Optional `adapter = "none"`, or the matching selected physical adapter ID when that port exists. Undeclared ports remain disabled.                                                                                                          |
| `[clipboard]`                         | Optional `policy = "disabled"` or `policy = "own_address"`. An explicit device file defaults to disabled when this table is absent. `own_address` permits only the deliberate copy action for the current profile's public contact address. |

`adapter` is a registered identity, never a Python import path. In simulator
mode, required display and input adapters are `simulator`, and physical bindings
are rejected. In physical mode, `[platform].adapter` (or legacy
`[display].adapter`) must match the required display/input IDs and the selected
`metor.platform_adapters` entry point. Discovery inspects metadata only, rejects
duplicate IDs and loads only that selected provider. The device file is
owner-checked deployment configuration; the package installation must also be
trusted. Neither an entry point nor a well-formed ID proves trust, and validation
after import cannot undo module import side effects. Optional capabilities are
off when omitted or explicitly `none`, even if the provider offers them; a
matching requested but unavailable capability fails before activation. Audio
and camera currently have no generic device adapter implementation: only
`adapter = "none"` is accepted for those tables. The display dimensions configure
the native Kivy/SDL window, not a supplied screen driver.

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

### Installed reference adapter and device settings

The harmless [`metor-reference-board`](../../examples/reference_adapter/pyproject.toml)
package implements the public SDK factory/session contract. In the same Python
environment as Metor, install it, create a private `device.toml`, and start the
GUI:

```sh
python -m pip install --no-deps ./examples/reference_adapter
cp docs/examples/gui-reference-board.toml ./device.toml
chmod 600 ./device.toml
metor chat --ui gui --device-config ./device.toml
```

On Windows, use `Copy-Item docs/examples/gui-reference-board.toml device.toml`
and launch `metor-gui.exe --device-config device.toml` or the common CLI from
PowerShell. The adapter package entry point registers `reference-board`; the
example file selects it with `[platform]`, validates
`[platform.config].initial_brightness`, and leaves all physical actuators off.
Open Settings → Device → Hardware settings → Simulated brightness. Apply a value
from 0 to 100. The adapter independently validates and reads back the effective
value. It stores the nonsecret simulation in the user's private
`~/.metor-reference-board/brightness.txt`, independent of any communication
profile. A second local GUI sees changes on entry to Settings or **Reload device
settings**. The example's input port reports released buttons only; it drives no
real screen, GPIO, indicator, haptic device, power switch, audio or camera.

The selected provider is trusted, nonprivileged application code running in the
local GUI process. Its `prepare()` validates parameters before `open()` can
acquire resources. `close()` releases resources after GUI consumers stop and is
safe against in-flight setting calls. Profile changes do not reopen the adapter.
For exclusive resources, the plan supplies a stable `resource_id` and requests
an OS-backed per-user lock; another GUI gets a clear busy error. A shared
provider such as this simulation declares shared use and must itself supply one
device-wide source of truth. An OS device service must enforce ownership across
users as well. In-process operations and cleanup must be bounded and cooperative;
a Python thread timeout cannot stop a hung native driver. Hardware I/O runs off
the GUI event loop. Setting descriptors are bounded boolean, numeric or finite
choice values; the GUI shows confirmed effective readback or an explicit
unsupported, denied, unavailable, failed or unknown outcome. Shutdown and purge
stay in their dedicated authorization and confirmation flows, never as setting
keys.

### Local service proxy pattern (illustrative)

A deployment may instead install a trusted `metor.platform_adapters` provider
whose typed ports act as a small local IPC proxy. The OS deployment manager
starts a separate, resource-limited device service; neither the GUI nor the
communication daemon starts it from TOML. The proxy may send a fixed operation
such as `set_brightness` with one validated integer from 0 to 100 over an
owner-controlled Unix socket or Windows named pipe. The service applies its own
size and time limits, verifies the peer using OS credentials or endpoint ACLs,
authorizes that specific operation, and reports the effective readback. A
verified local service may hold narrowly scoped device privileges without
granting them to Metor or reading its profiles, keys or messages. This is an
integration pattern, not a supplied production service. Do not load untrusted
Python/native drivers in GUI or Core, or assume that a separate process with
the same broad rights is a complete sandbox. IPC carries only bounded data and
defined operations, never scripts, import paths, pickled objects or general
commands.

## Navigation and communication

The root is a DROP/LIVE communication overview, with access to Notifications,
Saved Contacts, and Settings. DROP and LIVE are distinct projections of the
same peer. Opening a view, changing a selector, Back, unlocking, or reattaching
does not connect, reconnect, accept, disconnect, change route, or fall back.
Those actions require explicit controls and typed Core commands. The GUI does
not infer online presence from a cached connection or change delivery semantics
because a view changed.

DROP and LIVE tabs within a peer replace the current projection in navigation
history. Back returns to the view that opened that conversation, regardless of
tab switches. The conversation header keeps one persistent status and the
explicit Start/Cancel/End Live, Call, and More actions in the same order and
location at narrow and wide widths. Short timelines align at the top from the
first layout; overflowing timelines follow the latest edge only while the user
has chosen to follow it.

An admitted Start Live action changes its visible controls before the next
native frame, even while Core is still processing the request. Connection
progress and failure stay in that header. Retry becomes available only after
Core confirms an eligible state; repeated clicks cannot start another attempt.
A connection failure for a conversation that is no longer visible produces one
contact-scoped transient result. Recovery does not create a new call invitation.

Switching between DROP and LIVE for the same peer retains its already-loaded
latest DROP page while refreshing it. The two native views are reused within
that conversation; the inactive view releases focus and pending input. Leaving
the conversation or covering the GUI revokes both views and their private text.
Other peers, profile changes, privacy covers and confirmed deletion cannot reuse
that page. A first read displays
`Loading messages…`, an empty confirmed page displays `No Drops yet`, and a
failed read provides an inline Retry action. Retrying the read never resends or
consumes a message.

Successful text and Voice sends are acknowledged by the message and its delivery
state, without an additional `Queued` or success toast. Send rejection and
unknown outcomes remain beside the affected draft or recording until resolved;
the content is retained. Editing or explicitly retrying clears an obsolete
draft error. Background reconciliation does not repeatedly extend a transient
notification.

Other action results that need a separate acknowledgment appear once in a
dismissible overlay and expire after six seconds. The overlay stays inside the
foreground content viewport, above fixed input controls, including in the wide
master/detail layout. Long result text scrolls within that bounded surface. If
the keyboard leaves less than a full dismiss target of space, the transient
overlay stays hidden and retains its original expiry; actionable composer and
connection errors remain inline. Navigation and privacy covers revoke overlays.
Ongoing connection, recording, sending, and unknown-result states belong to
their corresponding controls, rather than repeated global banners or
Notification Center entries. Background reads do not disable foreground actions;
confirmed mutations invalidate older read projections before those can overwrite
the result. A newly opened archive receives the next free read turn after exact
action reconciliation; general background reads otherwise retain fair admission.
Message-only changes request fresh
data without rejecting in-flight reads or regressing confirmed delivery receipts;
contact changes and mutations still invalidate the affected projections.

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

Enter sends the focused message draft; Shift+Enter inserts a newline. Both the
physical and local keyboard follow this rule. A pending send remains tied to
its original message identity and cannot be repeated; an unknown outcome is
checked through read-only reconciliation without resending the message.

Confirmed DROP sends refresh the open archive without requiring navigation or
a prior LIVE connection. Explicit successful Send as Drop opens that peer's DROP
projection so the converted item is visible under its preserved identity.

## Contacts, notifications, and settings

Saved Contacts is the address book. Discovered peers appear in communication
views only while Core reports relevant state. Contact add, rename, removal,
and promotion use Core identity and results. Removing a saved contact can demote
its label without disconnecting active communication; old aliases must leave
notifications, accessibility nodes, and cached presentation. A QR scan is an
explicit camera action using the accepted contact format, bounded validation,
and the user's current intent. It cannot execute a URL or command, duplicate a
saved identity, or start a LIVE chat without an explicit Start Live intent.
Address regeneration is a confirmed profile action and does not imply that old
contacts or conversations move automatically.

Confirmed contact changes update every open label in the same GUI turn, without
waiting for another snapshot. Display names retain the user's capitalization;
lookup and duplicate detection compare Unicode case-folded names. The canonical
peer identity is independent of that display name.

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
failures. Initial supported service and device metadata resolve behind one
loading state before the complete settings layout becomes interactive. Later
reloads retain visible controls, scroll position and keyboard focus.
Accept calls without unlocking, lock notification privacy,
application idle timeout, profile-name visibility, keyboard layout, and pins are
independent protected preferences. Accept calls without unlocking defaults Off;
LIVE auto-accept never grants conversation audio. A profile password is the
default unlock method. Core-owned receipt, fallback,
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

Both DROP and LIVE Voice use Record → Stop → Preview → Send or Discard.
Releasing GUI or hardware PTT stops recording and opens review; it never sends.
Preview and received messages play only after a manual Play action. Listening
to the whole draft is unnecessary for sending. Before explicit Send, bytes stay
in protected local Core staging. Capture and finalization cannot publish them.
If LIVE ends during recording or review, the draft remains unsent and offers
explicit reconnection or Send as Drop. That action preserves the draft identity.
Owner loss freezes uncommitted drafts; a later authenticated client must explicitly claim the exact interrupted recording for review or discard it.

Playback and range reads do not implicitly consume Voice. Release follows the
public safe handoff contract. Scroll and playback positions are separate; the
waveform is not a redundant keyboard focus target. Headset selection remains
distinct from proven speaker echo cancellation.

Telephone calls use a separate Call action in contacts and DROP/LIVE chats.
A direct call requires one call acceptance and keeps the selected message mode.
A call from LIVE requests additional audio permission; rejection or hangup keeps
the accepted chat. The call view offers status/duration, mute/unmute, cancel,
reject/accept and hangup according to Core state. Only accepted calls start
local duplex audio, using the explicitly configured headset endpoints. Calls
have no replayable Voice card, conversation recording or Send as Drop action.
Transport loss ends the call; reconnecting a chat never reopens or accepts it.

No microphone or camera starts on boot, navigation, reattach, or unlock.
Permissions are requested at explicit use. Missing optional media capability
leaves text usable and offers setup through the deliberate media controls;
media execution stays unavailable until its requirements are satisfied.

Missing audio is explained only after a deliberate record, play, or call action,
in a closed dialog with **Go to audio settings**. Settings → Device → Audio
settings opens the same closed configuration dialog. Microphone and headphone
selection each open a separate device chooser and return to configuration;
closing the dialog removes the chooser completely. The composer has no permanent
setup banner, and call readiness does not create action feedback or notifications.
Audio dialogs keep a bounded stable frame while device results update inside
their scrolling content. Refreshing a dialog preserves Close and Back/Cancel
input ownership; refreshed confirmation actions require a new deliberate press.
Playing a supported Voice message with no output configured uses that recovery
dialog. Selecting a route never starts capture or playback;
the user initiates the next recording or Play action.

## Privacy and lifecycle

Notifications contain no message body or Voice preview. Notification Center,
playback position, consumed LIVE presentation, and other GUI caches are bounded
volatile state. Application lock covers pixels, accessibility text, tooltips,
input, media, and indicators before private content can leak. A restricted
client is distinct from a hard-locked profile runtime. Message capture and
playback stop for every delivery mode; accepted prefixes remain protected,
unsent drafts. A held PTT must be released and freshly pressed after unlock.
Unlock restores the preview but never starts capture, playback or sending.
An already accepted call continues through application/screen lock with its
mute state intact. Its reduced view contains status/duration, mute and hangup,
with identity filtered by notification privacy. Accept calls without unlocking
allows explicit acceptance of only that exact call; the rest stays covered.
Hard profile lock, profile switch, client loss and purge end the call. System
suspend ends real-time audio rather than replaying a backlog after resume.
The Linux logind/screen-lock and Windows session/power adapters distinguish
screen lock from suspend; physical continuation requires a named native run.

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
Desktop and simulator defaults permit an explicit Copy address action for the
current profile's public contact address. An explicit device file must set
`[clipboard] policy = "own_address"` to permit it; `disabled` (or an absent
clipboard table in that file) prohibits the action. Generic text fields,
messages, and credentials cannot be copied through the GUI. After an allowed
copy, the host clipboard may retain the address beyond GUI lock or exit.
Volatile application state is not a promise against host swap, screenshots,
crash dumps, or physical media recovery.

## Lock and control semantics

Application Lock or short configured Power restricts this client while the
daemon and other authenticated clients may continue. It does not issue a Core
hard-lock command. Core validates PIN, password, cooldown, and locked-action
scope. A PIN cannot authenticate a cold or new client, and PIN-only access
cannot weaken profile credentials. Forgot PIN requests a password challenge.
An unconfirmed restriction stays covered and cannot create a second
unrestricted connection. App restriction permits neither LIVE invitation
acceptance nor message media. Automatic LIVE acceptance is chat permission only.
An active call's exact client and call identity own its limited exception;
ending it cannot grant access to a later call from the same peer.

The software keyboard is local and offers QWERTY and QWERTZ without cloud
suggestions or a learned persistent dictionary. Desktop typing uses the
physical keyboard by default. It opens on field focus only when the device
configuration declares touch input; no keyboard button occupies the field.
Focus order follows visible reading order;
selection alone does not start communication. A focused PTT control may own
Space down/up, but text fields and global shortcuts cannot capture that press.
The text composer uses Enter for explicit Send and Shift+Enter for a newline.
Incoming call UI does not steal an active typing or PTT owner. Modal focus
returns to a safe invoker; Escape/Back closes a reversible overlay before
navigating and cannot dismiss a privacy cover or accepted destructive work.
Closing an action sheet removes its input surface immediately; an invisible
closing animation cannot intercept the next foreground action.
Master navigation returns Back to the active DROP/LIVE overview. Selection
of secondary header actions follows the foreground section; the master
DROP/LIVE mode and its accent start action remain selected independently.
Back leaves the current page and clears its list selection; the separate Cancel
selection action stays within the list. Keyboard focus survives a repaint of
that same route and clears when the route changes. Detached controls cannot
activate from a delayed pointer or keyboard release.

Pointer actions show hover and press feedback while preserving the current
typing owner; keyboard navigation retains its visible focus ring. Recovery
snapshots do not reopen LIVE invitation presentation, and ended requests are
excluded from call selection. Read-only snapshot and page loading do not disable
foreground actions.

## Design and accessibility

The minimum usable client rectangle is **360 × 640 logical units**, excluding
window decoration and platform insets. Below 960 logical width, use one
foreground panel; from 960, a 360-unit master pane may stay beside the detail.
Crossing the breakpoint preserves route, selected IDs, focus, drafts, and
scroll anchor without a communication command. Controls must remain operable
at 1.5 text scale and with long content; wrap or grow rows and scroll forms
instead of shrinking text or hiding required actions. A keyboard inset must not
cover focused input or required actions.
Entry, lock, and profile management content stays fixed when it fits the
viewport. Scrolling is enabled only for actual overflow, including locked
activity or accepted-call controls. Pending profile activation shows covered
progress until a graphical prompt or the complete profile becomes available.

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
into a media owner. For a peer opened from the master list, compact Back returns
to the originating root tab and wide Back clears the detail to a neutral
conversation prompt. A peer opened from a contact picker returns to that picker;
switching DROP/LIVE within the peer does not add a navigation step. Contacts,
Notifications, and Settings replace the foreground detail,
while authentication, restriction, profile transition, and purge cover the whole
application. Desktop master tabs stay available on secondary pages; selecting a
tab changes the list while preserving the foreground page. Selecting a
conversation or New Drop/Start Live opens its destination on the first click.
Incoming-call presentation cannot obscure or steal an existing
PTT owner. Confirmation and authentication sheets show the relevant current
identity and consequence; stale asynchronous results cannot close a newer
sheet or reveal an old profile.

Message rows grow with content. Own and incoming direction, DROP/LIVE delivery,
local acceptance, pending, delivered, read, and failed outcomes remain
visually distinct without relying on color alone. Available timeline timestamps
show local hours and minutes for today's messages and add the calendar date for older
messages. History always includes the date; canonical message timestamps remain
unchanged for exports and handoffs. The text composer, recording
state, DROP Voice review, and playback controls are separate states. Timeline
scrolling and audio seeking have separate affordances. Status notices align
with the active content column and do not create extra communication actions.
Message and conversation menus sit inside their surface. Voice waveforms do
not take keyboard focus; Play and the explicit message actions remain separate
keyboard targets.
Required controls stay visible or reachable at the minimum viewport and text
scale. Buttons and touch targets use at least 48 logical units where the
current component permits it; labels wrap or controls stack when necessary.
Conversation names and secondary navigation headings share the peer-title
typography. Titles, status text and adjacent actions stay vertically centered
within their row; wrapped text grows the row rather than shifting its controls
or shrinking the font.

The packaged Inter Tight face is the visual baseline. The current core palette
uses background `#101619`, surface `#171F22`, primary text `#F3F7F6`, DROP
`#4ED7C8`, LIVE `#FFB454`, danger `#FF6474`, and success `#72D68C`.
Components may use related surface and outline tokens, but privacy, delivery,
and authorization meaning must stay legible in native rendering, with keyboard
focus and accessible names. Reduced motion preserves all state and safety cues.
