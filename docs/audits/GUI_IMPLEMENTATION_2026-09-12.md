# GUI implementation and acceptance report — 2026-09-12

**Incomplete development implementation. Functional/design acceptance is OPEN.**
The requested complete GUI has not been delivered. Passing baseline regressions,
installed-package tests and a native renderer slice do not complete WP-G2–G5 or
the required V/A/S/L inventories. This report records the actual work and the
remaining gates; it does not amend either approved specification.

Latest full-suite checkpoint: **621 tests pass in 579.804 s**
(`/tmp/metor-gui-resend-regressions.log`). It includes the profile host/catalog,
phase-aware switch, GUI-only desktop close, password-verifier correction,
delivered-own resend, root recency, media ownership and accepted regressions.
The newer purge milestones, receipt reconciliation and bounded contact management
have focused passing evidence below and are undergoing another full run.
Current mypy covers 428 source files. Boundaries and generated-document
reproducibility pass; packaging and complete acceptance work continue.

The authorized native Windows GUI Razer capture/review now passes: 37,120 bytes,
1,160 ms, actual SDK/temporary encrypted Core, no message publication or audio
export. The test uses synthetic focused keyboard input and source-checkout code;
it is not final installed-bundle, physical-key, AEC or full-duplex acceptance.
Detailed profile, password and Windows evidence appears at the end of this report.

Earlier settings/history and native checkpoints below remain historical evidence;
they do not replace the current mandatory-open inventory.

Native 360 × 640 and 1024 × 768 at 150% pass held-End identity and calling Cancel
keyboard probes. The minimum-size/150% settings editor preserves input/focus,
rejects invalid integer input and submits its original displayed expectation.
The activity-history native capture exposed a collapsed single-line alias height;
the corrected layout preserves separated alias and display-time rows at 150%.
These are synthetic native inputs and public DTOs, without microphone or peer
transport. Current settings/history captures and environment records are retained
alongside the lifecycle captures; full V17–V19 layout acceptance remains open.
History native keys verify reachable pagination, retained scroll after a rebuild,
Cancel as the initial Enter target and exactly one explicitly confirmed clear.
Current captures: [settings editor](gui-2026-09-12/native-setting-editor-150.png)
and [activity history](gui-2026-09-12/native-history-150.png), with matching JSON
environment records; both use synthetic DTOs and no actual Core mutation.
After the 594-test checkpoint, modal keyboard placement and a persistent edit
scope footer were added. The [native touch fixture](gui-2026-09-12/native-setting-keyboard-150.png)
types through the ordinary modal veil and keeps field/Save/Cancel reachable at
minimum size and 150%. Existing composer-keyboard, confirmation and continued-PIN
native probes pass after this change. Protected GUI preference unknown-response
readback was also added afterward: all **5 settings tests pass in 25.046 s**,
including failed-read retry without a repeated write.
The timeout editor now has a separate [native failure fixture](gui-2026-09-12/native-timeout-editor-150.png):
unsaved input/focus survive a snapshot, disabling lock needs a second explicit
confirmation, and a correlated rejection preserves the open editor and value.
Notification, profile-name, unlock-method and keyboard preferences use scoped
rows. Current Ruff/format and mypy checks pass (410 source files).
The current ordinary-framebuffer captures are
[compact](gui-2026-09-12/native-live-controls-compact-150.png) and
[wide](gui-2026-09-12/native-live-controls-wide-150.png), with matching JSON
environment/geometry records. End is visually disabled in their restored inert
simulator state; the separately injected native interaction probe enables the
control and checks its captured identities without actual transport.

Previous full-suite checkpoint: **568 tests passed in 352.555 s**
(`/tmp/metor-gui-restricted-final-regressions.log`). This includes continued
restricted media, exact cross-client call acceptance, bounded notification
sources and the foreground-action admission fix. The preceding full run passed
566/567 and exposed an Unlock admission race behind a background restricted
query; this was corrected rather than weakening the existing security test.
The new deterministic admission regression and all five real GUI security
integration tests pass. Ruff, mypy (388 source files), boundary checks and
generated documentation freshness/reproducibility pass at this checkpoint.
Current root projection tests pass 3/3; real encrypted Core DROP cleanup tests
pass 2/2 in 12.123 s. They verify direction-qualified same-ID deletion, pending
preservation, protected unpinning, review staging survival and exact volatile
media cleanup. Peer/message More and Privacy clear actions now use shared
scope confirmations. LIVE fallback/close action tests pass 4/4 in 12.475 s,
including actual IPC. Complete lifecycle/native/resource-pressure acceptance
remains open.

Native SDL fixtures use synthetic input/DTOs, independently of Core and hardware
proof. Continued recording at 360 × 640 / 150% shows a non-identifying danger
dot, accepted-time timer and release target. Native Shift+F10, right-click,
500 ms hold, movement beyond 8 units and detached-target cancellation pass in
`tests/gui_native_context.py`; explicit modal-to-incoming switching preserves
Cancel safety. The Notification Center has a summary-aligned chevron and its
menu is at most 320 units wide. Bundled SVGs now use semantic currentColor,
including disabled tones; native center bindings avoid stale icon placement.
The minimum-size PIN/continued overlay passes native scroll reachability checks:
Unlock and Forgot PIN remain 48-high and above the media strip after scrolling.
Anonymous activity updates preserve native PIN focus. These fixtures and gesture
results are retained under `docs/audits/gui-2026-09-12/`. The test exporter now
renders the unchanged native canvas without a negative Y transform: Kivy's
default flipped rendering clipped offset stencil regions on this software GL
backend. PNG row orientation is applied by the native image writer; no fixture
widgets or reference pixels are substituted. Further comparison exposed cached
stencil artifacts even with positive-coordinate subtree export and an offscreen
drawable retaining its initial size. The current fixture sizes SDL before its
first window and captures the ordinary drawn native framebuffer region directly.
The 360 × 640 / 150% DROP capture now contains the complete header and selector.
Older subtree PNG exports are not treated as definitive visual acceptance and
must be refreshed before final reporting.

The root fixture exercises 130 summaries with 64/64/2 attached native row counts,
exact last-page navigation and page restoration. It waits for descendant layout
work before capture. Its measured process RSS is about 460 MB after repeated
synthetic page construction, independent of the much smaller logical payload
budgets; this is recorded evidence, not a target-device memory acceptance claim.
Native settings rows grow at 150% and align the trailing value with the measured
title/help group. Safe Core descriptor editors and metadata history are implemented.
Full GUI preference presentation, profile/power/purge flows and complete native
responsiveness/resource-pressure testing remain unfinished.

Windows endpoint enumeration still returns no Razer BlackShark route at this
checkpoint. The owner's headset authorization remains valid, and the earlier
isolated native duplex result remains recorded separately; the full GUI headset
capture/review check has not passed and is not replaced by synthetic audio.

## Baseline, authority and provenance

- Branch: `embeddedui`. Starting and current HEAD:
  `0cfa122a47c879106b86de9578439df6ffc10b7c`. Changes are in the working tree;
  there is no ending implementation commit, release or tag.
- Functional v1.0 SHA-256:
  `8907c510aeb7cf9272816e60bd1c09a2f38c31c7d340d67859163254f2c8cca7`.
- Layout v1.0 SHA-256:
  `3202019b3fd3e7aef472d281006cdb35c1caf073dbaaf2ee75bf691eeaadf5b0`.
- Both complete inputs were read. Their durable `docs/specs/` copies and original
  `docs/.temp/` inputs are byte-identical. The latter were not edited.
- Application/SDK/UI version 0.2.0; launcher 2; IPC current/minimum 2;
  peer current/minimum 3; DB current 4/minimum 3; keyslot/blob/derivation generations 1.
- Penpot MCP inspected the specified file, five pages and twelve pinned board
  structures. Current file revision was 69. The named saved v0.7 revision exists
  at 2026-09-11T21:45:01.685Z. The available API lists historical versions but
  restores them by mutating the shared design; no restore or design edit ran.
  Current viewport exports are comparison evidence, not verified historical
  snapshot bytes. The written v1.0 corrections take precedence.
- The root and active-LIVE reference viewports were inspected. Missing forms,
  keyboard/privacy variants and layout corrections remain defined by v1.0;
  Penpot access limitations do not waive them.

The [integration map](../contracts/GUI_INTEGRATION_MAP.md) records actual public
interfaces and unresolved Core/host additions. [GUI.md](../contracts/GUI.md) is
the durable runtime entry point. The old Embedded contract has a historical
GUI-assignment pointer while its still-current neutral Core behavior is retained.

## Implementation and ownership

`metor-ui-gui` owns only `metor.ui.gui`, its native components and offline assets.
It has independent lazy entry-point registration. Optional defaulted
`FrontendLaunchContext.device_config` and `.simulator` fields extend the Python
launcher contract without changing existing callers. Protected metadata adds
defaulted IPC-2 DTOs and requires schema 4 with migration from 3; application,
peer, keyslot and derivation versions remain unchanged.

The GUI package separates runtime/prompt work, presentation state, platform
configuration/audio, widgets and views. SDK and base remain frontend-neutral;
GUI imports use public SDK facades. No database, Tor, profile-file or daemon
implementation is accessed by GUI code. No shadow history/preferences store,
plaintext pin sidecar, purge bypass or replacement transport was introduced.

Kivy 2.3.1, sounddevice 0.5.3 and qrcode 8.2 are the pinned runtime dependencies.
Inter Tight source and four real static weights, Lucide sources/native SVGs and
licenses have 77 checked local SHA-256 asset records. Native SVG rendering still
has an optical/stroke conflict described below. A packaged extra-glyph fallback
is not implemented. The qrcode dependency is present but the own-identity QR
widget and complete contact flow are not implemented.

Kivy is untyped. Mypy ignores missing stubs for those external dependencies and
allows subclassing their dynamic widget classes only in `gui.widgets.*`,
`gui.views.*` and `gui.app`. State, platform and SDK orchestration retain strict
checking. This is an adapter boundary, not a whole-GUI typing exemption.

The existing release builder was reviewed for cohesion before extension. Its
change is bounded variant selection/asset cleanup, not another orchestration
subsystem. A separate builder/extraction would duplicate ownership. Canonical
`all`, CI and release validation now include four distributions; publication
was not run. SDK/base/Terminal-only variants remain available.

## Work packages

| Package | Actual status | Remaining gate |
| --- | --- | --- |
| WP-G0 | Baseline/spec/Penpot inspection, versions, initial gates and integration map completed | No acceptance inferred from historical audits |
| WP-G1 | Partial: independent installed native GUI, common CLI launch, strict config, simulator, graphical SDK prompt bridge, candidate audio port | Physical adapters, canonical Windows installer and complete platform acceptance |
| WP-G2 | Partial: generation/context identities, bounded handoff/drafts/inventory, protected preferences, Core descriptors, exact continued restriction and local text/Voice ownership | Exact unknown cleanup/fallback readback, complete cache/overload/lifecycle matrix |
| WP-G3 | Partial: root/peer projections, contact intents/QR validation, incoming handles, shared context actions, qualified lifecycle and metadata history | Delivered-own resend, complete message gestures, large contacts and full native V/A/S/L acceptance |
| WP-G4 | Partial: PCM capture/playback, PTT source arbitration, owned review/commit, accepted-prefix recovery, coverage gates and fallback | Real GUI headset/duplex, full seek/auto-play/large-item pressure and physical driver failure matrix |
| WP-G5 | Partial: profile switch/desktop exit, lock/setup, protected policies, continued-context revocation and bounded private notifications | Physical power/purge and complete OS/multi-client acceptance |
| WP-G6 | Partial: earlier canonical four-package build/install checks, docs migration, tokens/assets and native compact/wide/150% probes | Final-source bundles, all layout/state families, responsiveness/accessibility and native Windows/device release acceptance |

## Executed evidence

Linux execution used WSL2 kernel `6.18.33.2-microsoft-standard-WSL2`, x86-64,
AMD Ryzen 7 7840HS, Python 3.11.15, Kivy SDL2/OpenGL with
`SDL_VIDEODRIVER=offscreen`. This is Linux process evidence, not Windows Python
evidence. PortAudio reports V19.6.0-devel, revision
`396fe4b6699ae929d3a685b3ef8a7e97396139a4`, and zero Linux audio devices.
`/dev/snd`, `/dev/input`, GPIO and video endpoints are absent.

| Command / check | Result |
| --- | --- |
| Initial `ruff check src/metor scripts tests` and format check | PASS; 324 files formatted |
| Initial `mypy src/metor scripts` | PASS; 294 source files |
| Initial full unittest discovery | PASS; 462 tests, 90.900 s |
| Earlier slice `ruff check src/metor scripts tests` | PASS |
| Earlier slice `ruff format --check src/metor scripts tests` | PASS |
| Earlier slice `mypy src/metor scripts` | PASS; 317 source files |
| `python scripts/check_boundaries.py` | PASS, including the new GUI tree |
| `python scripts/versioning.py validate` | PASS |
| `python scripts/validate_generated_docs.py` | PASS; initially fresh and reproducible through canonical generators |
| `python scripts/check_release_compatibility.py --current docs/generated/compatibility.json` | PASS; no previous public release, current manifest is baseline |
| Earlier slice full unittest discovery | PASS; 482 tests, 98.507 s; predates metadata/security extensions |
| `python scripts/build_release_wheelhouse.py --variant all --skip-pip-upgrade --output-dir /tmp/metor-gui-bundles` | PASS; four Linux dependency-closed ZIPs |
| GUI variant rebuilt after bootstrap/native fixes | PASS; same canonical builder |
| `python scripts/validate_wheel_versions.py /tmp/metor-gui-bundles/*/wheelhouse/metor*.whl` | PASS; coordinated versions and disjoint files |
| `python scripts/validate_installed_artifacts.py /tmp/metor-gui-bundles` | PASS; offline fresh installs, positive/negative external SDK typing, dynamic IPC, Terminal help loop, both UI removal orders, SDK-only survivor |
| `python scripts/validate_release_installers.py /tmp/metor-gui-bundles` | PASS; actual Linux installers for SDK, base, Terminal and GUI |
| Installed common CLI/native launch without device file | PASS in Linux offscreen desktop mode; no runtime/profile activation |
| Installed common CLI/native launch with `--simulator` | PASS in Linux offscreen simulator mode; isolated temporary data root |
| Native widget key-repeat and focus-loss probes | PASS using synthetic events on real Kivy widgets; not physical input proof |
| Audio PCM frame/seek/timing and resource cleanup tests | PASS; sample framing is real, stream cleanup uses mocks |
| Windows Razer microphone/playback | PASS: explicit endpoint duplex port probe, 33,280 captured bytes discarded, 32,000 output bytes, 1.375 seconds; GUI PTT/acoustics/AEC not verified |
| Full GAT and L acceptance | NOT PASSED |

The SDK GUI bootstrap test uses a real loopback SDK transport with scripted
strict auth/snapshot/inventory DTO responses. It proves the graphical prompt
bridge and wire-client path. It is not a real GUI-to-Core/Tor communication
scenario. The retained preexisting Core tests remain regression evidence for
their own enclosing paths, not proof that unimplemented GUI actions work.

An initial sandboxed regression invocation could not bind required local
sockets and was stopped. The authorized native run passed. The first expanded
suite found one existing mock assertion requiring the two new optional launch
arguments; that assertion was migrated and the full final suite passed. Native
captures first included six surplus vertical pixels from the simulator bar;
the bar and captures were corrected. These earlier results are superseded,
not silently treated as successful final runs.

Installed captures use `/tmp/metor-gui-installed/bin/python -I`, cwd `/tmp`,
without editable installs/PYTHONPATH and without Terminal. To reproduce, copy
`tests/gui_native_capture.py` and `tests/gui_installed_launcher.py` outside the
checkout, use a non-editable offline GUI installation, select the intended
SDL display, and run the former with `--view`, `--width`, `--height`, `--output`.
The launcher fixture runs the real common CLI, actual registered frontend and
native event loop, then closes it through a scheduled callback. Each invocation
uses a temporary profile root and creates no real communication or power action.

## Foundation extension verification (work in progress)

Protected metadata tests: eight passing real-SQLCipher migration/CAS/authorization
tests. The first expanded 489-test regression run found 12 snapshot failures
caused by a key-reopening metadata adapter. The adapter now uses storage's active
repository; all 19 existing closure integration tests pass again. The following complete run passed 492 tests in 122.748 seconds. Subsequent
text acceptance/receipt reconciliation and pin cleanup pass 34 GUI tests in
46.051 seconds. Their complete regression passed 496 tests in 138.501 seconds; rebuilt
artifact validation remains required for these extensions.
Earlier package/renderer results above describe the earlier built slice.

Windows native evidence uses an isolated official Python 3.11.9 embeddable
runtime in `/tmp/metor-gui-windows/runtime`, with native Windows dependency
wheels and installed base/SDK/GUI wheels, without Terminal. The official archive
SHA-256 is `009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b`.
The real common CLI entered and closed the SDL event loop. A native 480×800 root
capture used a 480×824 window including the simulator bar, RSS 169,906,176 bytes.
The portable runtime is test infrastructure; canonical Windows installers and
uninstall semantics still need validation.

The owner approved the Razer BlackShark headset route. The installed candidate
PortAudio adapter ran concurrent capture/output for a bounded one-second quiet
tone, then closed both streams. Captured bytes were counted and discarded; no
microphone payload was saved. See
[probe result](gui-2026-09-12/windows-headset-audio.json). This is native device
evidence, distinct from still-unimplemented GUI PTT and Core staging integration.

## Visual and memory evidence

| Capture | Exact inner viewport | RSS observed | Scope |
| --- | --- | --- | --- |
| [Root](gui-2026-09-12/root-480x800.png) | 480×800 | 179,085,312 bytes | Synthetic published DROP rows |
| [DROP](gui-2026-09-12/drop-360x640.png) | 360×640 | 174,698,496 bytes | Short/wrapped text, measured bubbles |
| [Desktop LIVE](gui-2026-09-12/live-1180x760.png) | 1180×760 | 194,363,392 bytes | 360 master + 1 divider, explicit header End Live |
| [Entry failure](gui-2026-09-12/failure-360x640.png) | 360×640 | 169,500,672 bytes | Covered bootstrap failure, no private underlying pane |

JSON beside each image records the actual window/viewport and evidence type.
The simulator surround is excluded. The figures are sampled process RSS, not
peak memory, per-resource accounting, large-media stress, input latency or
physical-appliance measurements. No latency/AEC/frame-rate target is claimed.

Visual acceptance remains open. Observed differences include overly heavy/
aliased native SVG strokes, missing icon tooltip/screen-reader integration,
selector inset/optical corrections, root action placement, complete row/status
decorations and compact composer alignment. The software keyboard, large-text
stacking, held-PTT resize, preserved focus/scroll anchors, anonymous/Off screens,
record/review/selection states and the required failure family are not complete.
Inter Tight and content-sized bubbles are implemented; that does not imply
L01–L18 pass. Full L-family status is explicitly OPEN, with these images as
partial evidence for root/text/basic failure/desktop portions only.

## Concrete unresolved integration and software work

The following obligations remain open despite the implemented paths and focused
regressions described above. Earlier checkpoint omissions have been replaced by
this current inventory; they are not competing implementation requirements.

1. V20 profile catalog/forms and phase-aware profile switching are now implemented,
   along with GUI-only V21 desktop close and full-password changes. Nine host/GUI
   catalog tests pass (0.304 s); eight lifecycle/identity tests pass (48.701 s),
   including a successful switch between separately encrypted Core runtimes.
   Native profile rows and rejected rename editor have 360x640/150% evidence.
   Appliance power, stopped-runtime address-rotation entry, all lifecycle failure
   combinations and the complete settings/history scale matrix remain open.
2. Native GUI headset capture/review now passes on Windows. Real duplex playback during transmission,
   driver-loss recovery, complete timeshift/partial-playback coverage and media
   pressure tests remain required. Accepted-prefix recovery, exact DROP review,
   bounded playback and PTT ownership have actual Core integration evidence.
3. Delivered-own-LIVE resend now has actual Core and native menu evidence (see
   the 14 September resend checkpoint). Complete waveform/seek presentation and
   selected-message gesture equivalence remain unfinished.
   Unknown DROP deletion/clear and fallback now use exact receipt readback for
   captured GUI identities; complete failure/pressure combinations remain open.
4. Root LIVE canonical recency and same-count local transcript invalidation are
   implemented; full large-list resource/latency evidence and scroll preservation
   still need completion.
   DROP membership/pins and 64-row native pagination are implemented.
5. Contacts now have bounded pages, Remove selected and independent QR decode
   evidence. Optional camera integration and the complete stale-action/scale
   acceptance matrix remain open.
   Save/Open/Start intent, canonical mutation guards, rename/demotion and local
   QR generation already have implementation and focused evidence.
6. Continued media and incoming-call privacy require the complete duplex,
   revocation, expiry, auto-accept and physical-input matrix. Native PIN focus,
   exact recipient handles, bounded notifications and Core revocation are
   implemented; they do not prove all combinations or appliance behavior.
7. V22 authorized physical purge arbitration, combined safe-destruction milestone
   handling, registered local power and concrete device adapters remain open.
   No ordinary desktop purge trigger or authorization bypass exists. Destructive
   verification must use isolated temporary profiles, never owner data.
8. Allowed clipboard export with ownership-aware cleanup, full untrusted-text
   font fallback/accessibility, responsive state preservation and complete
   L01–L18 optical/interaction fixtures remain open.
9. Rebuild all four distribution bundles from final sources and repeat installed
   consumer/co-install/removal checks. Earlier Linux/Windows launch artifacts are
   stale relative to current changes. Canonical Windows installer and final
   native dependency checks remain required.
10. Full GAT/V/A/S/L evidence, p95 latency, baseline/peak RSS and bounded queue
    occupancy under continuous media and realistic lists remain open. Current
    native synthetic fixtures and Core regressions are separately scoped proof.

These are mandatory implementation obligations, including software work that is
independent of missing hardware. Neither approved input has been weakened.

## Requirement traceability

Ranges below are inclusive. Every listed requirement remains an **open acceptance
gate** unless the evidence is explicitly limited to an executed subcheck.
An implementation location is not a pass. These groups cover all 99 named
functional requirements without replacing their original text.

| Functional IDs | Current implementation/evidence | Unresolved owner/work package |
| --- | --- | --- |
| GUI-PROD-01–06 | Root/peer presentation and navigation tests | Complete product/privacy semantics, G2–G5 |
| GUI-ARCH-01–04 | `packaging/gui`, lazy launcher, common CLI and installed gates | Native platform completeness, G1/G6 |
| GUI-START-01–06 | CLI resolution, strict parser, no-file and simulator native launch | Full desktop controls, physical registered ports, G1 |
| GUI-API-01–04 | Integration map, stable profile instance, controller/mailbox and public SDK bootstrap | Complete inventory/media reconciliation, G2 |
| GUI-DATA-01–04 | Bounded volatile drafts, protected preferences, Core disposable producer journal | GUI media lifecycle and full lock/purge hygiene, G2/G5 |
| GUI-BOOT-01–03 | Entry forms, graphical prompt bridge and failed-attach cleanup | Complete startup routing, setup, typed failure handling, G1/G2 |
| GUI-NAV-01–05 | Root/peer routes, protected pins, 64-row paging and no-call navigation | LIVE recency, full V inventory and pressure/scroll matrix, G3 |
| GUI-ACT-01 | Explicit action submission and text identity barrier | All A actions and lifecycle-scoped identities, G2–G5 |
| GUI-FLOW-01–03 | Intent picker, exact incoming handles, qualified End/Cancel/Change route | Complete expiry/auto-accept/native lifecycle matrix, G3/G5 |
| GUI-INPUT-01–05 | Local keyboard, focused PTT, source ownership and held-release regressions | Full physical/duplex/restriction input matrix, G3/G4 |
| GUI-VOICE-01–05 | Owner-qualified PTT/review, journals, interrupted recovery and explicit finalization retry | Native headset and complete owner-loss/pressure matrix, G2/G4 |
| GUI-AUDIO-01–06 | Bounded incremental playback, manual priority, foreground auto-play and exact consume tests | Partial coverage, waveform, native duplex/seek/pressure matrix, G4 |
| GUI-MSG-01–05 | Text handoff, qualified DROP cleanup, fallback/dismissal, delivered-own resend and exact unknown-result receipt reconciliation | Full gesture/media/failure matrix, G3/G4 |
| GUI-NOTIFY-01–05 | Bounded no-preview center, source watermarks, restricted privacy and exact call navigation | Complete pressure/staleness/privacy combination matrix, G5 |
| GUI-LOCK-01–05 | Protected setup, same-client restriction, PIN/password, exact continued media and Core revocation | Full physical/duplex/OS-event combinations, G2/G5 |
| GUI-CONTACT-01–04 | Saved intent flows, guarded rename/demotion/bulk removal, bounded pages and independently decoded native QR | Camera, full scale/stale-action matrix and regeneration, G3/G5 |
| GUI-HISTORY-01 | Bounded summary/technical Core metadata pages, retention flags and confirmed full ledger clear; real pagination/uncertain-clear tests | Complete native failure/scale matrix, G3/G5 |
| GUI-SET-01–04 | Protected defaults/CAS, full-strength policy auth, safe Core descriptor editor, exact receive scope and stale/unknown saves | Complete GUI preference C12 and native modal keyboard/settings matrix, G2/G5 |
| GUI-LIFE-01–04 | Profile switch and GUI-only close implemented with typed phases and owner cleanup | Prepared physical power and complete lifecycle failure matrix, G5 |
| GUI-PURGE-01–03 | Existing authorization preserved; actual Core scoped runtime-release/combined-safe reports tested | Physical binding, chord arbitration and GUI power integration, G2/G5 |
| GUI-SAFE-01–03 | Local assets/plain labels; credential/composer export disabled | Complete clipboard/accessibility/rendering and status semantics, G3/G6 |
| GUI-PLAT-01–06 | ADR, parser, candidate native port, support manifest/RSS samples | Physical adapters, duplex acoustics, latency/buffer stress/indicators, G1/G4 |
| GUI-DESIGN-01–04 | Approved copied packet, Penpot inspection, four native fixtures | Complete layout/state/asset/accessibility realization, G6 |
| GUI-DONE-01–03 | Package/docs/report and explicit evidence levels; non-goals excluded | Full mandatory implementation and acceptance remain open |

### View, action and state inventories

| IDs | Status and implementation location / missing behavior |
| --- | --- |
| V01–V03 | Partial `views/entry.py`; setup/routing/recovery incomplete |
| V04–V05 | `views/security.py` and `runtime/security`: protected setup/restriction, PIN/password and continued strip; full native/physical matrix pending |
| V06–V09 | `views/root.py`, `views/peer/`: pins/paging, text/media and exact lifecycle actions; remaining recency/resend/coverage/pressure work |
| V10 | Incoming overlay, independent privacy, exact handles and nonmodal focus behavior; full expiry/auto-accept matrix open |
| V11–V13 | `views/contacts/`: saved intent picker, manual/QR validation, save/rename/demotion; bulk management open |
| V14 | Open: camera/QR entry absent |
| V15 | Local address/QR generation implemented; independent decode and address regeneration open |
| V16–V17 | Bounded Notification Center, protected preferences and safe Core descriptor editors implemented; full matrix open |
| V18–V19 | Bounded activity/technical history and platform diagnostics implemented; complete native state/scale matrix open |
| V20 | Implemented bounded catalog/forms and phase-aware switch; full scale/failure matrix and stopped-runtime rotation entry remain open |
| V21 | Partial normal window detach; prepared exit/power absent |
| V22 | Open: purge view/state absent |
| V23 | Partial explicit config/display errors and bootstrap error cover |
| A01–A04, A08, A11 | Partial route/explicit command/text submission boundaries; full eligibility/reconciliation missing |
| A05–A07, A09–A10 | Exact accept/decline/open-call, qualified route change and ended-context close implemented; complete race matrix open |
| A12–A22 | PTT/play/review, fallback/delete/clear and application lock implemented; delivered resend and full media acceptance open |
| A23 | GUI-only finalization/owner release/detach, one draft-loss confirmation and protected recovery exit choice implemented; full native failure matrix remains open |
| A24–A25 | Open: physical shutdown/purge not bound |
| S01–S07 | Partial loading/empty/busy/error/unknown/stale presentation; full identity and input retention not implemented |
| S08–S09 | Partial draft/mailbox rejection and unavailable media labels; media interruption and adapter recovery absent |
| S10–S11 | Partial authorization restriction/challenge/cooldown; complete lifecycle families pending |
| S12 | Local LIVE text acceptance and exact-ID reconciliation tested; complete media truth pending |
| L01–L18 | All open; four illustrative native captures do not meet the family inventory |

### GAT test groups

These are test-group statuses, not a count of passing individual unit tests.
Existing Core regressions are not substituted for enclosing GUI scenarios.

| GAT IDs | Evidence and remaining acceptance |
| --- | --- |
| 01 | Root/Back projection, no implicit communication, native paging and lifecycle refresh checks; complete navigation/focus matrix open |
| 02–03 | Saved search/manual QR validation and preserved Save/Open/Start intent implemented; camera and independent QR decode proof open |
| 04–06 | Exact pending handles, calling Cancel, explicit Accept/Open and stale lifecycle tests; complete simultaneous-peer matrix open |
| 07–09 | Independent capture/playback workers and bounded foreground transcript implemented; real duplex/time-shift matrix open |
| 10–12 | Actual Core owned capture/review/finalize/commit and native PTT ownership probes; full physical/media failure matrix open |
| 13–16 | Selective/bulk fallback and ended-context dismissal tested; delivered-own resend and exact unknown-fallback readback open |
| 17–19 | Public contact intents, stale rename guard and shared context actions implemented; large-list selection/remove/camera matrix open |
| 20–23 | Core restricted continuation, policy authentication, anonymity and native PIN overlay tested; complete physical lock/feedback matrix open |
| 24–27 | Open: full profile switch, phase-aware exit, safe power and physical purge |
| 28–30 | Owner-loss preservation, bounded foreground text handoff and metadata history implemented; complete restart/retention/playback matrix open |
| 31–32 | Earlier Linux installed CLI/GUI and four-wheel ownership/removal checks pass; final-source artifacts and Windows co-install/removal remain open |
| 33–34 | Selection/help regressions and lazy installed GUI help checked; complete native dependency-failure permutations open |
| 35–38 | Desktop offscreen launch, strict simulator config and scripted graphical SDK bootstrap checked; full real-profile/device/remote matrix open |
| 39–42 | Optional route failure is explicit, simulator inert and absent output cannot consume; native adapter and complete graphical auth/loss matrix open |
| 43–44 | Public retained inventory, bounded DROP paging, separate media/state ordering and exact context revocation tested; complete growing-media ordering matrix open |
| 45–46 | Bounded queues, duplicate/unknown text/settings/history controls and stale lifecycle qualifiers tested; full overload catch-up and all mutations open |
| 47–51 | Core producer isolation, owned PTT, review collision, admission/IO/finalization/commit failure and explicit recovery tested; complete process-kill and physical-input matrix open |
| 52–55 | PCM alignment, finite range playback/cache, manual priority and coverage gates implemented; large-item/native seek/auto-play/pressure matrix open |
| 56–60 | Restriction failure, exact continuation revocation, notification staleness/Off and anonymous-handle races tested; full simultaneous media/lock matrix open |
| 61–62 | Protected SQLCipher metadata/CAS/migration, policy auth and stable profile identity tested; full profile-switch phase failures open |
| 63 | Per-client detach/owner release implemented; phase-aware close UI and complete multi-client active-capture scenario open |
| 64–66 | Open: physical Power/purge arbitration, authorized platform binding and truthful destruction milestones |
| 67 | Protected defaults, registry-derived safe Core descriptors, exact Receive Drops scope and stale/unknown saves tested; full native settings/policy matrix open |
| 68 | Plain bounded rendering, local assets, strict QR parsing and clipboard restrictions implemented; full hostile-text/accessibility/allowed-clipboard matrix open |
| 69–70 | Multiple-size native framebuffer, 150% editor/history and lifecycle/gesture probes; every V/A/S/L state and responsiveness/accessibility matrix still required |
| 71–72 | Isolated authorized Windows Razer native duplex probe passed earlier; real GUI capture/review and complete physical support proof open |
| 73 | Earlier four Linux ZIP installer/consumer checks pass; final-source rebuild and canonical Windows installer execution open |
| 74 | Runtime/map/ADR/schema/sample/support, contract migration and generated settings/API are updated; documentation must continue tracking remaining implementation |
| 75 | Inventories map actual evidence and explicit remaining gates; complete product acceptance remains open |

## Producer lifecycle implementation checkpoint

`test_gui_producers.py` passes eight tests against actual authenticated Core IPC,
SQLCipher and encrypted blob objects (50.813 seconds before final bootstrap
wiring). The tests cover owner-token isolation, inventory qualification,
per-peer draft collision, screen-lock preservation, explicit release, actual
IPC disconnect, preserved generic drafts and committed DROP winners, failed
blob cleanup after receipt removal, pre-write allocation failure, a fresh
owner service and explicit interrupted LIVE recovery. The fresh-service test
does not claim an actual process-kill/restart result.

Owner cleanup runs in Core and survives GUI loss. Every owned object ID is
journaled before bytes are written. Canonical committed/accepted data is
excluded from destructive cleanup; unaccepted allocation debris stays tracked
until deletion succeeds. Failed LIVE finalization retains bytes and projects
`producer_interrupted` / `can_retry_finalization`. Purge keeps its existing
preemption fence. Ordinary release uses the existing runtime-release result;
failed cleanup does not falsely report a clean hard-lock teardown.

The GUI now registers its public disposable lease during bootstrap and requests
owner-qualified inventory. Close requests release on the departing connection;
disconnect invokes Core recovery if the response is unavailable. Capture,
review/playback and complete exit-choice views are still pending. The implementation
and ownership rationale are in the integration map. Schema 4 includes producer
claims alongside metadata, with the same explicit transactional 3-to-4 migration.

Canonical generators refreshed the API/schema/compatibility artifacts; freshness
and reproducibility passed. Ruff, strict source mypy, architecture boundaries and
the version registry passed. Previously built Linux/Windows installed artifacts
predate these Core and GUI changes and must be rebuilt before final acceptance.

After final producer/bootstrap wiring, full unittest discovery passed **504 tests
in 187.829 seconds** (`/tmp/metor-gui-producer-regressions.log`). Strict
`mypy src/metor scripts` passed for 338 source files. These results include the
existing regression suite; they do not close the remaining GUI acceptance groups.

## PTT worker implementation checkpoint

The GUI now contains a pure one-source press machine and a bounded capture
worker, connected to controller navigation, composer exclusion and lock
deferral. Four press tests passed. Four GUI capture/real-Core tests passed in
25.816 seconds, including DROP review on release, empty cancellation, lost
append response without retransmission, and navigation preserving the original
target with a release barrier. The microphone in these tests is explicitly a
finite synthetic frame source. Native audio evidence remains the earlier Razer
port probe; it is not upgraded to GUI PTT evidence.

Public LIVE-context generation and exact retained-ID filtering support safe
admission and reconciliation. The context-token test passed after adding a
same-connection barrier for post-response cleanup (7.132 seconds). Thirty
existing Core closure tests passed in 28.133 seconds. Strict source/script mypy
passed for 341 files, and Ruff passed. Native recording controls, route selection,
review actions, playback and full timeline integration are still pending.

The next full suite passed **515 tests in 230.009 seconds**
(`/tmp/metor-gui-current-regressions.log`), including receipt enum decoding and
review reconciliation. The focused lost-review-commit test passed in 6.506
seconds. Subsequent changes extracted profile activation, added an input-identity
bridge across widget/profile replacement, and added deferred bounded native
endpoint enumeration; those changes require their subsequent enclosing checks.
Five pure press/input-bridge tests pass. No native PTT or playback acceptance is
claimed from these controller and synthetic microphone tests.

## Native input and playback implementation checkpoint

The peer pane now retains composer/PTT widgets and chronological message objects
across background updates. Native SDL synthetic-key tests passed for repeated
Space, release after focus loss, held-key transfer from a text field, and five
successive repaints retaining the same focused PTT object. Source-native renders
at 360×640 include the voice card and at 480×800 include the unsent DROP review.
They were visually inspected; the waveform, full scale/accessibility matrix and
physical input acceptance remain open. Artifact paths at this checkpoint are
`/tmp/metor-gui-voice-360x640.png` and `/tmp/metor-gui-review-480x800.png`.

Eight deterministic playback/auto-play tests passed (0.016 seconds). They cover
full output before exact release, cache replay, output failure, unsupported codec,
read completion after departure, skipped-prefix non-consumption, incomplete edge,
closed-cache rejection, context-default inheritance, recovery, foreground/manual
priority and queued stale-generation rejection. Six actual GUI capture/Core IPC
tests passed in 41.478 seconds, including previewing an owned DROP through the
real public SDK while its canonical status remains draft. Those tests use explicit
synthetic microphone/output ports and do not claim a native acoustic round trip.

Ruff and strict source/script mypy pass for 356 source files. The enclosing full
regression run is in progress. Existing installed artifacts predate these changes.
Required text handoff, pagination, complete lifecycle/notification/settings views,
native media stress and the remaining acceptance rows are still open. This is an
implementation checkpoint, not the required final completion report.


## Handoff, keyboard and page-navigation checkpoint

The enclosing handoff/keyboard regression run passed **528 tests in 248.096
seconds** (`/tmp/metor-gui-handoff-keyboard-regressions.log`). The previous 525-test
run exposed one stale bootstrap test patch after the documented activation
extraction; its patch target was migrated, and all 17 GUI contract tests then
passed. Three bounded handoff tests passed against temporary encrypted Core IPC,
including a protected consumed result arriving after route departure and cover.

Native 360×640 keyboard renders at normal and 150% font scale were inspected:
`/tmp/metor-gui-keyboard-360x640.png` and
`/tmp/metor-gui-keyboard-360x640-scale15.png`. Both assert a 264-unit dock, 8-unit
composer gap and at least 48 units of timeline. A 160-item native fixture retained
64 widgets, its older-page anchor and the independent new-items affordance.
These are synthetic-input/source-native fixtures, not installed-device evidence.

Four subsequent archive/page tests passed in 12.256 seconds using actual Core IPC
for bounds, direction-colliding IDs, older pages, unchanged unread counts, old
writer defaults and departed-route result rejection. The new page changes still
require their enclosing regression and updated installed-artifact checks.

The approved Razer BlackShark was absent from the subsequent Windows endpoint
list. The new native GUI capture/review probe stopped before opening any input;
reconnection was requested while other implementation work continued. The earlier
standalone Razer duplex port result remains valid and does not become GUI recording
evidence. No microphone content was exported.

## Contact workflow and native form checkpoint

Five contact tests passed in 11.957 seconds after fixing broadcast correlation.
Two use real temporary encrypted Core IPC: a save completes the original DROP
intent only after acknowledgment, and a stale alias cannot rename/remove a peer
that acquired the label. The remaining tests exercise production GUI intent
handling for self/rejected/unknown save, active LIVE without another ring, and a
failed start remaining in the picker. The initial failing removal test revealed
that orphan cleanup could complete a generic correlated request before the real
rejection; that defect was corrected at the database event-publication boundary.

Source-native renders were visually inspected at 360×640:
`/tmp/metor-gui-contact-form-scale15.png` (150% text),
`/tmp/metor-gui-contact-qr.png`, and `/tmp/metor-gui-contact-sheet.png`.
The sheet artifact exports its actual content panel because exporting a native
ModalView itself does not correctly frame its window-relative canvas. Captures
now wait three stable layout frames before judging wrapped input text. The
contact address remains complete canonical field content; no width-driven text
rewrite is used. QR pixel rendering is verified; an independent decoder round
trip remains pending.

The expanded native keyboard fixture passed actual key-widget editing across
native layout frames: QWERTY/QWERTZ, single-use Shift, double-activation Caps,
all ASCII digits/punctuation, masked PIN input, Backspace, focus retention and
explicit Hide. The 150% render is unchanged after the transient secret field is
cleared and removed. Enter-on-focused-PTT is separately rejected by the native
input fixture. Eight playback tests also passed (0.022 seconds) after restricting
auto-play eligibility to connected or genuinely recovering contexts.

The full regression run including contact and archive changes passed: 537 tests
in 273.454 seconds (`/tmp/metor-gui-pages-contacts-regressions.log`). This remains an open
implementation checkpoint; it does not close the remaining functional/layout,
notification, lifecycle, device, resource or installed-artifact acceptance rows.


## Notification, confirmation and exact call checkpoint

The six Notification Center tests passed in 0.050 seconds. Native compact normal
and 150% selection renders were inspected. Entries retain no message previews;
Clear/Dismiss affect only presentation and unchanged-source watermarks. Locked
notification accumulation and full source-change stress remain open.

The native confirmation fixture passed at 360×640 with 150% text: initial focus
is Cancel; native Enter does not confirm; privacy-cover reconciliation clears the
sheet's private body. The narrow actions stack with primary above Cancel and
remain within the viewport. Evidence: `/tmp/metor-gui-confirmation.png` and its
JSON metadata. This is native SDL rendering and synthetic native input, not
physical device evidence.

Seven call tests passed in 24.156 seconds. Four use actual encrypted Core IPC
and controlled socket pairs: recipient ownership, replacement safety, source
projection races, anonymous denied Accept followed by normal unlock, and
accepted-context navigation identity. Three use the production GUI state flow
with synthetic DTOs to check Accept versus Open, multiple request selection,
stale Open and privacy sanitization. The tests assert typed Core rejection
results; generic `IpcEvent` requests intentionally return those outcomes.

A full regression run including the notification implementation and session
access extraction is in progress (`/tmp/metor-gui-calls-regressions.log`).
Native incoming-call renders are also being checked. These checkpoints do not
close continued locked LIVE, lifecycle/device, media-pressure, installation or
remaining functional/layout acceptance rows.


The native 360×640 call renders passed with the actual SDL renderer:
`/tmp/metor-gui-incoming.png` at 150% text and
`/tmp/metor-gui-incoming-anonymous.png` at normal text. The incoming fixture
checks that arrival does not call recording departure and preserves the native
focused draft. The call panel uses 24-unit internal/outer insets, fixed reachable
actions, measured title wrapping and 48-unit Previous/Next icon targets.

The first full call checkpoint ran 550 tests in 299.581 seconds with one failing
expiry fixture. Its fake pending dictionary retained Bob while emitting an
expired event. The fixture now removes that request before publication, keeping
its existing independent-handle and rejection assertions. Production expiry
projection deliberately refuses to revoke a still-current replacement request;
a new real-Core test covers that race explicitly. A replacement full run is
required after this correction and the cohesive pending-state extraction.


The corrected full call checkpoint passed: **551 tests in 304.508 seconds**
(`/tmp/metor-gui-calls-final-regressions.log`), including the network pending-state
and session-access package extractions. Generated references are fresh and
reproducible; Ruff, source/script mypy and distribution boundaries passed.
The minimum-size 150% native keyboard fixture also passed after adding the
nonmodal overlay (`/tmp/metor-gui-call-keyboard-regression.png`).

Subsequent text changes reserve one exact outgoing transcript slot and its
serialized payload budget before Core admission. Early Read/ACK metadata updates
that reservation; positive Read/Delivered evidence does not regress on later
ACK, inventory or acceptance results. A full transcript refuses the send before
Core mutation and retains the draft. Four focused state tests passed in 0.001
seconds, and five real Core security/text tests passed in 40.093 seconds.
These later text changes are not included in the preceding 551-test full run.


## 2026-09-14 profile and desktop lifecycle checkpoint

V20 now uses the optional host catalog through finite typed mailbox results,
including startup selection without blocking the native GUI thread. Local
create/rename/remove/default operations retain original selected-host context;
unknown mutation results require readback before another explicit mutation.
Forms preserve name input on rejection and clear secret fields at admission and
cover. Native close routes through capture finalization and owner release without
requesting global profile exit. Explicit switch uses the accepted SDK coordinator
and complete target hydration. Actual source preparation and client release are
distinguished; lost preparation responses never imply safe rollback.

Focused evidence: `test_gui_profiles.py` 9/9 in 0.304 s;
`test_gui_lifecycle.py` 8/8 in 48.701 s; existing graphical SDK bootstrap 1/1 in
5.393 s. The successful switch test uses independent temporary encrypted Core
runtimes and different passwords. The native profile editor proves exact original
rename/selection and focus retention after a synthetic changed-state refusal.
[Profile rows](gui-2026-09-12/native-profiles-150.png) and
[rename refusal](gui-2026-09-12/native-profile-editor-150.png) are actual SDL
framebuffer captures at 360x640/150%, with adjacent machine-readable metadata;
no Core or physical hardware operation is performed by those fixtures.

The full regression checkpoint passes **612 tests in 618.411 seconds**, including
the optional authenticated-client count. This run predates the subsequent
password-verifier correction: an additional real authentication test showed that
the pre-existing password-change handler retained the old active verifier after
rewrapping storage. Its correction and focused follow-up are recorded separately;
612 passing tests must not be represented as coverage of that later change. Previous native Windows wheel artifacts are still stale.
These additions do not complete the mandatory device, media, layout or release
acceptance inventory above.


Password follow-up: the failing new authentication test confirmed that the old
password still opened a fresh session after storage rewrap. Core now installs a
new active verifier after rewrap and clears an uninstalled candidate on failure.
Focused password tests pass **2/2 in 32.331 s** and the accepted daemon password
regression passes **1/1 in 0.003 s**. Mypy passes for 419 source files; Ruff,
formatting (484 files), boundaries and whitespace checks pass. Full-suite 612
remains the preceding checkpoint; the additional authentication test makes the
next expected full count 613 at that checkpoint. No approved input bytes changed.

## 14 September resend and root checkpoint

Own delivered LIVE text and complete retained PCM now have an explicit new-ID
DROP resend path. Six focused tests pass (19.413 s), including actual Core
commit/append with their replies deliberately lost, receipt-only reconciliation,
explicit discard of an incomplete new copy, source eviction and privacy revocation.
Nine capture tests pass (57.715 s), including complete own LIVE cache retention and
unavailable source after a lost append acknowledgement. No peer or native microphone
is used by these tests. The earlier 612-test checkpoint predates these changes.

The native 360×640/150% menu fixture passes exact-target Enter/repeat, eviction
while open, received LIVE exclusion and same-count root invalidation. Evidence:
[`native-resend-evicted-150.png`](gui-2026-09-12/native-resend-evicted-150.png) and
[metadata](gui-2026-09-12/native-resend-evicted-150.json). The framebuffer was
visually inspected; controls and unavailable-source help fit the viewport.
Synthetic input and synthetic source descriptors are explicitly separate from
the actual Core tests and the previous Windows headset capture evidence.

Core snapshot LIVE ordering now uses canonical receipt/transport recency with
stable peer ties; GUI importance/pending priority remains intact. Root local-row
invalidation uses projected identities, and converted DROP turns no longer create
local LIVE ghost rows. Full regression and remaining acceptance work continue;
this checkpoint is not a completion or release claim.

The full resend/root checkpoint subsequently passed **621 tests in 579.804 s**
(`.venv/bin/python -m unittest discover -s tests -v`,
`/tmp/metor-gui-resend-regressions.log`). This includes the password verifier
correction, resend, capture-cache and root-recency work. It predates the following
purge-milestone and archive-receipt additions and is not their full-suite evidence.

## 14 September Core purge milestones

Five tests pass in 28.293 s (`test_gui_purge.py`): exact operation ID validation,
independent runtime/database/key failures, actual temporary encrypted-profile
destruction, failed runtime abort and cleanup failure after safety confirmation.
Core now exposes separate runtime-release and combined-safe milestones under
`purge_safe_milestone`. Keyslot removal alone never emits combined safety after
runtime release failure; plaintext profiles receive no encrypted-access safety
claim. No real owner profile or host power operation was involved. Physical
Power/PTT arbitration, appliance ownership and GUI power/purge remain open.


Native Windows GUI capture/review now passes. Evidence:
[headset result](gui-2026-09-12/windows-gui-headset-review.json) and adjacent native
view image. Official CPython 3.11.9 NuGet runtime, Kivy 2.3.1/SDL2/OpenGL, NVIDIA
RTX 4060 Laptop GPU, user-authorized Razer BlackShark MME input/output. The
focused synthetic Space press captured and reviewed **37,120 bytes / 1,160 ms**,
finishing in 3.968 s with **157,974,528 bytes RSS**. Real public SDK and temporary
SQLCipher Core were used. The canonical result remained an owned unsent DROP
draft, with no outbox publication and no microphone audio exported. This is
source-checkout integration evidence, not a final installed bundle, physical
PTT, AEC/acoustic-quality or full-duplex/driver-loss acceptance claim.


## 14 September pause and continuation handoff

The owner explicitly requested a pause and a summary for a later continuation.
The task is **not complete**. Changes remain uncommitted on `embeddedui`; do not
replace or discard this working tree. The approved temporary inputs and durable
`docs/specs/` copies still have their original matching SHA256 hashes. Resume
from this handoff and the two approved v1.0 specifications, preserving the
accepted architecture and regressions. Earlier open-item statements in this
report are historical checkpoints; the following is the current pause state.

### Verified at the pause

- Full contact/receipt/purge checkpoint: **630 tests passed in 679.047 s**,
  `/tmp/metor-gui-contact-lifecycle-regressions.log`. This checkpoint predates
  the subsequent playback-coverage and physical-button changes.
- Latest focused playback suite: **12 tests passed**. Drained PCM coverage is
  unioned across pauses/seeks, gaps and failed output never count, positive release
  metadata survives source eviction, and an evicted released source is not
  refetched. Ledger limits conservatively forget coverage instead of filling gaps.
  Latest log: `/tmp/metor-gui-playback-coverage-tests.log`.
- Physical button arbitration: **5 tests passed**, with no real driver/profile/
  shutdown port. Complete PTT/Power snapshots suppress simultaneous PTT admission,
  require five continuous chord seconds, consume cancelled/repeated edges, open
  the long-Power menu once at two seconds, and require observed release after
  input loss. This state machine is **not yet wired to a registered appliance
  adapter or the native GUI**. Log: `/tmp/metor-gui-buttons-tests.log`.
- Latest Ruff check passed; format check passed for **503 files**; mypy passed for
  **432 source files**; `git diff --check` passed. No new full-suite result is
  claimed for the final playback/button changes.
- Linux canonical SDK/base/Terminal/GUI bundles built; isolated installed consumer
  checks and both frontend uninstall orders passed; all four native offline ZIP
  installer checks passed. Artifacts are under `/tmp/metor-gui-bundles-linux`.
  Logs: `/tmp/metor-gui-{bundles,installed,installers}-linux.log`.
- Windows SDK/base/Terminal bundles built. The original all-variant build collided
  with regression tests using shared build directories. The GUI retry from an
  isolated source snapshot **built successfully**. All four ZIPs now exist under
  `/tmp/metor-gui-bundles-windows`; retry log is UTF-16 at
  `/tmp/metor-gui-windows/gui-build.log`. Canonical Windows installers and isolated
  coinstall/uninstall checks are **still unrun**. These are checkpoint artifacts,
  not final-source acceptance: rebuild after remaining production changes.
- Native contact paging/selection/search-focus fixtures passed at 360x640/150%:
  130 contacts render as 64/64/2 rows. Exact selected removal is bounded and lost
  batch responses stop mutation before read-only reconciliation.
- Independent zxing-cpp decoding of the native QR framebuffer passed; evidence is
  `gui-2026-09-12/native-qr-independent-decode.json`. Decoder/Pillow were temporary
  validation tools, not production dependencies.
- Previously documented native Windows Razer GUI capture/review remains valid.
  The owner authorized that headset route; do not ask for the same authorization
  again. It is not physical appliance, complete duplex or acoustic acceptance.

### Remaining implementation and acceptance work

1. **Appliance lifecycle and V21/V22:** implement validated local runtime/host
   binding and single-active-runtime ownership; integrate the tested button
   machine; request and obey scoped lifecycle grants; implement normal safe
   preparation/shutdown and the purge cover with exact operation milestones.
   The Core combined-safe foundation is implemented, but GUI handling currently
   closes on `SelfDestructInitiated`; it must retain the proper operation's event
   path until safety/cleanup outcome is known. EOF, keyslot-only, completed-only
   and timeout must never authorize shutdown. No destruction-status API exists.
2. **Concrete device integration:** registered schema-validated physical display,
   rotation/safe-insets, input and authorized power adapters; optional camera,
   indicator, haptics and clipboard policy as applicable. No physical adapter is
   currently registered. A missing-information question about available appliance
   hardware/access was sent earlier and remains unanswered. Desktop software
   work can continue without that answer; physical acceptance cannot be claimed.
3. **Voice/media:** waveform and deliberate seek presentation; complete coverage,
   live-edge and large-item streaming integration/stress tests; actual GUI duplex,
   receive indication during TX, driver loss/unplug and OS lifecycle behavior.
   Recheck coverage metadata revocation and bounded release-receipt eviction.
4. **Concrete newly noticed message-menu defect:** `views/peer/timeline.py`
   attaches message actions only for DROP or own pending LIVE rows. Own delivered
   LIVE resend is implemented in the menu/controller but must also be reachable
   from the actual delivered row. Fix both text and Voice conditions, verify native
   access, dynamic eligibility and all required gesture equivalents.
5. **Contacts and navigation:** expose the specified Scan/Enter entry and preserve
   its originating intent through unavailable-camera/manual flows; complete
   stale-action, focus, arrow navigation and scroll-anchor tests. Finish equivalent
   gestures and stable focus/anchors across root/message/contact updates.
6. **Profiles:** stopped-runtime address rotation and remaining full-profile
   failure, native form and scale matrix. Existing safe host operations, switch,
   password change and GUI-only close must retain their current semantics.
7. **Accessibility/layout:** complete required screen/state/action coverage and
   L01-L18 native comparisons, Unicode/font fallback, platform screen-reader
   exposure, reduced motion, focus trapping/return and responsive/keyboard matrix.
8. **Platform/release verification:** run Windows canonical offline installers and
   isolated installed consumers including both uninstall orders; repeat final
   installed GUI bootstrap/media with the final artifacts. Collect p95 input/
   render latency, peak RSS and queue occupancy under sustained workloads.
9. **Final integration and report:** reconcile stale historical matrix rows,
   complete all functional/GAT-01..75 and layout V/A/S/L mappings, finish contract
   migration/documentation consistency and generated-reference validation, rerun
   the required full regressions and final bundle checks, then write the specified
   completion report with explicit evidence and any remaining hardware limitations.

The temporary Windows runtime is the official CPython 3.11.9 NuGet distribution
at `/tmp/metor-gui-windows/nuget/tools/python.exe`; offline wheels are in the sibling
`wheels` directory. Use inline PowerShell through WSL (logs are UTF-16), and use
isolated source copies for builds so tests cannot clear their build directories.
No release, commit, real-profile purge or host shutdown was performed.
