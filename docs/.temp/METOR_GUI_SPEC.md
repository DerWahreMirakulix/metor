# METOR GUI SPECIFICATION
## Functional, interaction, platform and implementation contract

**Version:** 1.0  
**Date:** 11 September 2026  
**Status:** Final consolidated functional baseline for the next layout/design round and subsequent GUI implementation. This document does not certify a finished Core refactor or a finished GUI.  
**Product / distribution / frontend ID:** Metor / `metor-ui-gui` / `gui`  
**Suggested repository destination:** `docs/specs/METOR_GUI_SPEC.md`  
**Future companion:** `docs/specs/METOR_GUI_LAYOUT_SPEC.md`  
**Language:** Implementation, documentation, identifiers and user-facing application text are English.  
**Implementation prerequisites:** Accepted Refactor 2, this specification, and an approved companion layout specification.

> One privacy-first Metor GUI, with the same DROP/LIVE semantics on desktop and dedicated devices. Platform adapters change the hardware integration, not the communication product. Without a requested device configuration, an explicitly selected GUI opens a normal desktop window.

---

## Reading map

For the **layout/design round**, begin with the product rules (section 1), view/action inventory (sections 7–8), behavior (sections 9–19), and the design-packet contract (section 21). The remaining sections constrain implementation and testability.

For the **implementation agent**, all normative sections apply. Section 22 orders the work; section 23 defines test groups; Appendix A records resolved decisions; Appendix B maps the former specification.

### Contents

- [0. Document authority and how to use it](#0-document-authority-and-how-to-use-it)
- [1. Binding product decisions](#1-binding-product-decisions)
- [2. Package, launcher and command-line ownership](#2-package-launcher-and-command-line-ownership)
- [3. Desktop, device, simulator and `device.toml`](#3-desktop-device-simulator-and-devicetoml)
- [4. Public Core/SDK contract and integration rules](#4-public-coresdk-contract-and-integration-rules)
- [5. State lifetime, privacy and storage](#5-state-lifetime-privacy-and-storage)
- [6. Startup, profile entry and first-run setup](#6-startup-profile-entry-and-first-run-setup)
- [7. Information architecture and view identity](#7-information-architecture-and-view-identity)
- [8. Explicit communication and incoming-call flows](#8-explicit-communication-and-incoming-call-flows)
- [9. Text composer and PTT state machine](#9-text-composer-and-ptt-state-machine)
- [10. Voice capture, DROP review and draft ownership](#10-voice-capture-drop-review-and-draft-ownership)
- [11. Voice playback, auto-play, timeshift and consumption](#11-voice-playback-auto-play-timeshift-and-consumption)
- [12. Recovery, fallback, deletion and message status](#12-recovery-fallback-deletion-and-message-status)
- [13. Notifications and volatile Notification Center](#13-notifications-and-volatile-notification-center)
- [14. Application/device lock, PIN and locked LIVE](#14-applicationdevice-lock-pin-and-locked-live)
- [15. Contacts, QR, identity and activity history](#15-contacts-qr-identity-and-activity-history)
- [16. Settings, scopes and defaults](#16-settings-scopes-and-defaults)
- [17. Profile switch, GUI close and normal shutdown](#17-profile-switch-gui-close-and-normal-shutdown)
- [18. Emergency purge and physical-input priority](#18-emergency-purge-and-physical-input-priority)
- [19. Clipboard, rendering, permissions and safe wording](#19-clipboard-rendering-permissions-and-safe-wording)
- [20. Platform implementation, technical choices and resource bounds](#20-platform-implementation-technical-choices-and-resource-bounds)
- [21. Contract for the next layout/design round](#21-contract-for-the-next-layoutdesign-round)
- [22. Agent implementation work packages](#22-agent-implementation-work-packages)
- [23. Acceptance scenarios and required evidence](#23-acceptance-scenarios-and-required-evidence)
- [24. Definition of done and required deliverables](#24-definition-of-done-and-required-deliverables)
- [Appendix A. Consolidation decisions and superseded ambiguity](#appendix-a-consolidation-decisions-and-superseded-ambiguity)
- [Appendix B. Coverage of the original 75-section GUI specification](#appendix-b-coverage-of-the-original-75-section-gui-specification)
- [Appendix C. Required handoff documents and source provenance](#appendix-c-required-handoff-documents-and-source-provenance)

---

## 0. Document authority and how to use it

### 0.1 Two complementary specifications

This is the complete successor **functional and behavioral** GUI specification. It is not a review, a list of optional suggestions, a layout mockup, or another Core-refactoring assignment.

| Document | Owns | Does not own |
| --- | --- | --- |
| This specification | Product capabilities, navigation meanings, action eligibility, state transitions, privacy/security requirements, data lifetime, platform/startup behavior, implementation boundaries and acceptance criteria | Final pixel coordinates, exact typography, icon drawings, colors, component measurements or unapproved hardware claims |
| Future `METOR_GUI_LAYOUT_SPEC.md` | Approved screen compositions, responsive arrangements, dimensions, design tokens, visual states, accessible labels, iconography, asset specifications and visual acceptance fixtures | A different message lifecycle, weaker authorization, implicit networking, altered draft retention, hidden history, or removal of required actions |
| Accepted Refactor-2 public contract | Actual SDK imports, launcher interfaces, authenticated commands/results, persistence/reliability, capabilities, resource rules and safe lifecycle operations | Final screen design |

The layout designer can start from this document now. The implementation agent MUST use **both** final documents and the accepted public contract. It MUST NOT treat screenshots as permission to omit a required state or invent behavior absent from this specification.

If an approved layout intentionally changes a functional rule, first version this document and record that decision. A visually attractive mockup does not silently supersede security or product semantics. If a pictured button conflicts with action eligibility, correct the layout rather than bypassing the Core.

### 0.2 Precedence and scope

Explicit subsequent owner decisions take precedence. Otherwise, preserve Core security/reliability guarantees; use this document for GUI behavior and the companion for visual realization. Unresolved contract conflicts are recorded as integration gaps, not implemented as UI-side domain workarounds.

This document replaces `docs/.temp/EMBEDDED_UI_SPEC.md` as the active GUI assignment, including its conflicting clauses and scenarios. Keep the old document historical; do not ask a coding agent to merge two competing GUI specifications. Earlier GUI reviews are rationale, not additional competing requirements.

The name `embeddedui` may remain a Git branch name. `embedded` describes a deployment context, not a second official GUI frontend. The official frontend is `gui`.

### 0.3 Refactor-2 boundary

At preparation time, the verified remote `embeddedui` head remained `7804407593def11fcb6449f011bc92a9bc20e699`, before acceptance of the running second refactor. The original GUI source had Git blob `8a0c5b73ff994f4e2f0cc54ee94ec2213d640bcd`. These are provenance anchors, **not** the required future implementation checkout.

The implementation agent records the actual accepted starting SHA, SDK/IPC and launcher versions, namespace ownership and capability names. Use the real post-refactor public imports; do not mechanically restore old `metor.client` paths or impose an additional namespace migration.

This successor adopts the **prior-authenticated, scoped lifecycle-capability model** from Refactor-2 decision D01. Do not resurrect `daemon.self_destruct_requires_unlock` as a GUI-controlled bypass. Anonymous cold/hard-locked hardware purge is not part of this GUI release.

The GUI phase may add narrowly scoped public host/SDK integration that is genuinely required by this specification, with tests and documentation. It may not fork Core, inspect its private storage, weaken its authorization, or reopen a broad refactor to hide a missing capability. Section 4 defines mandatory integration contracts and gap handling.

### 0.4 Implementation gate and pre-release rules

Production GUI implementation begins after Refactor 2 is accepted **and** the layout companion is approved. A mock used in the layout round is not production acceptance evidence.

No compatibility layer or migration for obsolete unreleased development schemas is required. Preserve actual product functionality, Terminal regression boundaries, message identity and supported profile-security conversion. No release publication, real-profile deletion, real purge or host shutdown is authorized by this specification-writing or normal test task.

`MUST`, `MUST NOT` and `REQUIRED` are normative. `MAY` permits an implementation choice only within the stated boundary. Named UI strings specify meaning; final copy may be refined in the layout companion except where a distinction such as **queued versus delivered** is security- or correctness-relevant.

---

## 1. Binding product decisions

### GUI-PROD-01 — One compact communication product

The interface is a minimal, privacy-first, touch-first Metor messenger that is also usable with desktop mouse and keyboard. It is not a web dashboard, a generic desktop productivity suite or a transport debugger.

User-facing communication vocabulary is consistently **DROP** and **LIVE**. Do not rename one selector `CHATS | LIVE` or merge both projections into a single conversation history.

Core transport terms such as `session`, `tunnel`, `direct`, circuit IDs and socket state do not appear in ordinary communication UI. Technical diagnostics are the explicit exception.

### GUI-PROD-02 — Minimalism without hidden required capabilities

There is no additional Home screen and no persistent bottom navigation bar. The communication overview is the root. It provides DROP/LIVE selection and access to Notifications, Saved Contacts and Settings.

Secondary actions are contextual. A long-press, right-click or equivalent contextual menu can expose them; critical actions cannot depend on an undiscoverable gesture alone. The layout companion decides exact placement and affordances while preserving all specified actions.

### GUI-PROD-03 — Core truth, frontend presentation

Core owns identity, message IDs, delivery semantics, receipts, pending/unread state, contacts, resource admission, recovery, fallback, authentication, capabilities and profile lifecycle.

The GUI owns view selection, transient text drafts, in-runtime draft presentation, scroll/playback cursors, bounded volatile media copies, notification presentation, pin ordering and wording. Platform adapters own actual display/input/audio/camera/indicator and local power integration.

### GUI-PROD-04 — Navigation is not a communication command

Opening a peer, tapping a DROP/LIVE selector, Back, opening Contacts/Settings/Notifications, reattaching, unlocking and rendering a recovered context do **not** initiate a call, accept/reject, disconnect, reconnect, fallback or change route.

`Start Live`, `Reconnect`, `Accept`, `Decline`, `Open` on a pending call, `End Live`, `Send as Drop` and `Change route` are explicit actions. An intent-labelled picker may complete an explicit action without asking for a redundant second confirmation.

Ordinary navigation may end this GUI's own capture or playback where the specified input-safety rules require it. It does not implicitly end the peer's LIVE connection. Local daemon autostart and existing authorized DROP delivery are separate from starting a new peer LIVE connection.

### GUI-PROD-05 — Identity and semantics survive presentation changes

A logical message is identified by profile instance, peer identity, local direction and `msg_id`. Aliases are mutable labels. Runtime epoch and LIVE-context generation qualify transient state and permissions; they are not substitutes for persistent message identity.

Pending LIVE-to-DROP fallback preserves `msg_id`. An explicit resend of an already delivered own LIVE item is a new DROP with a new ID. No received LIVE forwarding or quoting is added in V1.

### GUI-PROD-06 — Privacy is not a theme

No message previews in notifications. No persistent Notification Center. No persistent GUI LIVE transcript, text draft, playback history or peer-activity side log. No client-side shortcut around PIN/password verification. No silent pending deletion, overwrite-oldest or expiry invented by the GUI.

Application-owned volatile state means the GUI does not write that content to persistent storage. It is not a claim that an arbitrary host operating system cannot swap, snapshot, log or dump memory. Hardened deployment controls and their tested limits must be documented separately.

---

## 2. Package, launcher and command-line ownership

### GUI-ARCH-01 — Separate distributions

| Distribution | Responsibility |
| --- | --- |
| `metor-sdk` | Public frontend-neutral DTOs, protocol/client, proof helpers, lifecycle interfaces and shared lightweight contracts |
| `metor` | Core, daemon, independent general CLI, application/local-runtime services and host-interface implementations |
| `metor-ui-terminal` | Existing Terminal chat, internal chat interactions and Terminal chat help |
| `metor-ui-gui` | This graphical frontend, its view models, packaged local visual assets and declared platform integration |

The GUI wheel depends on the accepted compatible base/SDK installation closure for normal `metor chat` use. Its runtime communication code consumes public SDK and injected host interfaces, not Core/daemon internals. It does not depend on `metor-ui-terminal`.

No UI extras, no `metor-ui-all` meta-wheel, no new separate daemon distribution and no overlapping ownership of installed Python files. A base-owned `metor-daemon` executable is not a separate daemon package and may remain as established by Refactor 2.

After real wheels are built, installing both official UIs is explicit:

```sh
python -m pip install --no-index --find-links ./wheelhouse metor-ui-terminal metor-ui-gui
```

This is a future wheelhouse installation contract, not a claim of present publication. Native dependencies for the chosen OS/architecture must actually be in the installable closure.

### GUI-ARCH-02 — Frontend selection belongs to the common launcher

For `metor chat` only:

```text
explicit --ui
    > METOR_UI
    > common client.default_ui
    > terminal
```

Use the accepted equivalent common setting name if Refactor 2 names it differently; do not create a competing GUI-local frontend preference.

A missing, broken, duplicate-provider or incompatible selected frontend is an actionable error. No silent switch to another frontend, no runtime package installation and no network lookup of package indexes.

`device.toml` never chooses between Terminal and GUI. Merely installing the GUI does not override the default or make unrelated CLI commands dispatch through it.

### GUI-ARCH-03 — Help and parsing stay independent

`metor --help`, `metor help`, `metor chat --help` and `metor chat --ui gui --help` use the common CLI help path. It does not initialize any GUI, read a device file, probe hardware, prompt for credentials, start a daemon or require a display. It works with the GUI wheel absent.

Chat help contains launch options only. Internal Terminal slash commands and shortcuts appear only in the running Terminal UI's own upper help area. They are neither GUI features nor shared CLI help.

Add any new launch options below to the accepted base parser and typed launch context. Do not scan/strip arbitrary `argv` tokens inside GUI code or import plugins to ask them to generate general CLI help. Unsupported options must be rejected according to the actual selected frontend, while help remains side-effect-free.

### GUI-ARCH-04 — GUI-first interactive bootstrap

After common parsing and launch validation, initialize the selected GUI sufficiently to display all interactive decisions. Profile selection/creation, password/PIN entry, missing-local-daemon confirmation and retry/cancellation take place graphically.

The injected host factory must support deferred, UI-supplied interaction. An already authenticated client can be supplied, but the launcher must not require a blocking terminal password prompt before the GUI can open. No `input()`/`getpass()` dependency in the graphical flow.

Preserve shared autostart policy: `never`, `ask`, `always`, with existing explicit start/no-start invocation overrides. `ask` shows an actual GUI confirmation. Remote endpoints never trigger creation of a substitute local daemon. Starting a daemon does not start a LIVE call or simulate a successful connection.

---

## 3. Desktop, device, simulator and `device.toml`

### GUI-START-01 — Final no-file behavior

**No requested device configuration means desktop mode.** The GUI opens a normal window using packaged desktop defaults and the approved layout's desktop sizing rules. There is no mandatory TOML file, missing-file dialog or automatic file creation.

Desktop mode is a normal usable product mode with real authorized Core communication. It is **not** simulator mode. A text-only environment may use text even if optional camera/audio hardware is unavailable.

### GUI-START-02 — Launch contract

The following are target CLI additions for the GUI phase; they are not claims that the pre-refactor parser already supports them:

```sh
# Normal desktop GUI; no file required.
metor chat --ui gui

# Dedicated device, explicitly configured.
metor chat --ui gui --device-config /etc/metor/device.toml

# Explicit non-destructive hardware simulation, same GUI.
metor chat --ui gui --simulator

# Simulate the declared device geometry/bindings without creating its real drivers.
metor chat --ui gui --simulator --device-config ./test-device.toml
```

Preserve existing profile/endpoint/autostart options. A device path is resolved from explicit `--device-config`, otherwise a nonempty `METOR_DEVICE_CONFIG`. No automatic search in the working directory, profile folder or system directories. In V1, there is **no implicit on-disk default device file**; an appliance service supplies its path explicitly. Unset the environment variable to use desktop defaults when it otherwise requests a device file.

Mode resolution after frontend selection:

1. Explicit `--simulator`: simulator, with optional validated device-description input.
2. Otherwise a requested device path: physical device mode.
3. Otherwise: desktop mode.

Explicit relative paths resolve against the invocation directory once and become absolute in the launch context. Device configuration is read-only to the GUI. An empty/malformed explicit path is an error, not absence. UI-specific launch options used with a real Terminal launch are usage errors; requesting help does not load a UI.

### GUI-START-03 — Errors and side-effect ordering

Validate a requested file and the safe schema before daemon startup, profile authentication, driver activation, capture, GPIO access or power-control binding. Lightweight selected-toolkit loading needed to render an error is permitted; it must not start those side effects.

| Condition | Behavior |
| --- | --- |
| No requested file | Desktop defaults, no warning |
| Requested file absent, unreadable, malformed or unsupported | Configuration error with the path and safe field/reason; no desktop or simulator fallback |
| Unknown/uninstalled device adapter or incompatible adapter schema | Explicit unsupported-device error; no mock replacement |
| No usable desktop graphical backend | Display-unavailable error; suggest Terminal/configured device display, do not claim TOML is always required |
| Optional capability unavailable | Disable/hide only dependent actions; text and unrelated actions remain usable |
| Required physical input/display or security-critical power binding invalid | Refuse physical device readiness and normal device operation |
| Runtime driver failure | Stop the unsafe action, show truthful capability failure; never claim successful recording/shutdown |

Example startup errors:

```text
Device configuration not found: /etc/metor/device.toml
Device mode was requested; desktop fallback is disabled.

No graphical display is available.
Use the Terminal UI or configure a supported device display.
```

A service deployment must surface early startup errors through its supervised log/status channel if no GUI can be displayed. Logs must not contain credentials, payloads or peer identities.

### GUI-START-04 — Device configuration schema, version 1

The device file selects registered platform capabilities. It does not configure message semantics, credentials, the active profile, peer destinations or GUI visual styling.

Top-level schema:

| Field/table | Required | Meaning / validation |
| --- | --- | --- |
| `schema_version` | Yes | Integer `1`; unknown versions fail explicitly |
| `[display]` | Yes | `adapter` registered ID; native `width_px` and `height_px` positive bounded integers; `rotation_deg` one of 0/90/180/270, default 0; positive finite `scale`, default 1; optional declared output identifier |
| `[input]` | Yes | Registered input `adapter`; adapter-validated `ptt_binding` and `power_binding`; touch availability. PTT and Power cannot resolve to the same physical control |
| `[audio]` | No | Registered `adapter` or `none`; input/output endpoint identifiers; declared routing/AEC policy. Absence means unavailable, not a fake working device |
| `[camera]` | No | Registered `adapter` or `none`; optional endpoint |
| `[indicator]` | No | Registered semantic indicator adapter or `none` |
| `[haptics]` | No | Registered adapter or `none` |
| `[power]` | No | Registered local shutdown adapter or `none`; absence disables platform shutdown and prevents a full-appliance-readiness claim |
| `[clipboard]` | No | `policy = "disabled"` by default; only the safe policies in section 19 are allowed |
| `[drivers.<registered_id>]` | Adapter-dependent | Parameters validated by that adapter's own versioned schema; unknown parameters fail |

Native pixel geometry describes the actual hardware. It is not a set of widget coordinates and cannot replace the layout companion's logical size, minimum-size and scaling rules. Unsupported geometry is a clear validation/compatibility result, not silently clipped controls.

The platform ADR in section 20 supplies the **actual** supported registered IDs and platform-specific binding syntax. These are bounded implementation choices because no physical board/driver stack has been selected by this product specification. Do not advertise placeholder adapter names as functioning hardware support. Ship a schema, a desktop-default description and an example file for every actually supported device adapter.

Configuration parsing is bounded: maximum 64 KiB file, finite collection/string limits, strict types, finite numeric bounds and rejection of duplicate/unknown schema fields. Document adapter-specific upper bounds. Do not evaluate code, arbitrary import paths, external URLs, command templates or shell fragments from TOML. Registered shutdown adapters use controlled platform APIs or fixed validated operations, not a shell command supplied by the device file.

Device files may not contain passwords, PIN/verifier data, keys, contacts, aliases, pinned Onion identities, messages, endpoint credentials or profile-selection state. File trust/access rules are validated by the host/platform integration. Do not elevate the entire GUI to root merely to enable an input driver.

### GUI-START-05 — Desktop controls and capability degradation

Desktop provides an on-screen hold-to-talk control when capture is supported, normal physical-keyboard input, mouse/keyboard-accessible contextual actions and an application-lock action. The layout companion defines the controls' appearance and location.

No global keyboard capture or interception of the host's physical Power button by default. An optional focus-scoped PTT shortcut must avoid text-entry collisions, ignore autorepeat and obey lost-release rules. Camera and microphone require an explicit user action before active capture.

No camera: manual supported contact-data entry still works. No microphone: sending text and available playback still work; PTT explains its absence. No playback device: text still works and Voice is not falsely consumed. Optional hardware must not be simulated silently.

### GUI-START-06 — Simulator containment

Simulator uses the same GUI views, action dispatch and state machines with explicit test platform ports. It displays a persistent, non-ambiguous simulator indicator outside normal peer content.

Simulated PTT, Power, LEDs, haptics, camera injection and local shutdown never call real device/power drivers. The purge chord is intercepted by the test harness and cannot send a real `SelfDestruct` to a production endpoint. Default fixtures/mock IPC are isolated. Integration tests may use real Core only in separately created, explicitly isolated temporary test profiles and must still use simulated host power.

No normal desktop invocation enables simulation. A loaded device description never causes real driver initialization in simulator mode. Simulation proves behavior, not actual hardware or acoustic performance.

---

## 4. Public Core/SDK contract and integration rules

### GUI-API-01 — Required capability map

The accepted contract must provide the following **semantics**. The names in parentheses refer to known predecessors where helpful; map to actual post-refactor API names in `GUI_INTEGRATION_MAP.md`.

| Capability | Required public behavior |
| --- | --- |
| Launch/host services | Typed launch context; deferred interactive client factory; profile inventory/create/manage through authorized host/SDK services; no private runtime object exposure |
| Attach/auth/restrict | Version/capability negotiation, full-password authentication, per-client restriction, normal reauthorization, PIN management with required stronger authentication |
| Runtime state | Authoritative content-free snapshot, epoch/context generations, ordered/scoped invalidations, retryable-unavailable result |
| Retained items | Bounded non-consuming inventory of pending LIVE, unseen Voice and Core drafts, with filters, pagination and exact identities |
| Message operations | Typed text send, filtered text handoff/consume, eligible local DROP delete/clear, selective/bulk fallback, disconnected LIVE dismissal |
| Media | Begin, bounded append with accepted offsets, finalize, non-consuming bounded read, explicit safe handoff/release, unsent DROP commit/cancel; recoverable failure states |
| Disposable GUI staging | Session/owner-qualified staging and cleanup; exact cancellation that cannot erase another client's draft; interrupted authorized LIVE capture cannot be silently discarded |
| LIVE operations | Explicit connect/accept/reject/disconnect/change-route; authoritative active/recovering/ended state and anonymous pending-request handles |
| Notifications | Content-free typed facts and permitted restricted projections; no notification database |
| Profiles/lifecycle | Phase-aware profile switch/graceful exit; distinct authorized purge with truthful destruction milestones |
| Preferences | Core settings descriptors and bounded, protected, profile-scoped GUI metadata via a public interface |

A missing capability is a named integration gap. The agent may implement a narrow, tested public extension in the correct owner and document it, but MUST NOT put reliability, PIN verification, message inventories, encrypted storage or authorization into the GUI. Security/reliability changes require their own traceability and Terminal regression tests. An unsupported mandatory capability cannot be hidden by shipping a fake successful screen.

### GUI-API-02 — Identity and cache keys

Use an opaque stable profile-instance ID supplied by the public host/SDK. Profile rename preserves it; creating a different profile with a reused name does not reuse its GUI data. Own-address rotation is not a profile identity change unless Core explicitly defines it as one.

Use `(profile_instance, peer_onion, direction, msg_id)` for message ownership and cache identity. Add the current runtime epoch and LIVE-context generation to transient operation/playback/permission tokens. Never target a destructive, fallback or replay operation by the current displayed alias alone.

Callbacks, requests, timers and completion handlers carry a GUI activation generation. An event from an abandoned profile/client instance cannot mutate the current view. Anonymous pending-call handles are not stable peer IDs and cannot be persisted or reused for later calls.

### GUI-API-03 — Bootstrap and race-safe reconciliation

1. Establish the public transport and negotiate required versions/capabilities.
2. Authenticate for the selected profile and register the relevant client/event subscription.
3. Buffer permitted events within declared bounds.
4. Obtain and install an authoritative snapshot using the SDK's state ordering contract.
5. Reconcile retained-message/media inventories without consuming them.
6. Apply remaining state deltas and media/request results using their own identity/cursor rules.
7. Only then enable actions requiring authoritative state.

A content-free snapshot supersedes only state facts that it actually represents. Never drop Voice chunks, text-handoff payloads, command replies or destruction results solely because an envelope revision is at/below the snapshot revision. Media catch-up uses IDs and offsets; repeated frames never play twice.

Epoch changes revoke old permissions and callbacks. Reattach and profile return must not automatically connect/reconnect/fallback. Already authorized Core recovery/delivery is displayed, not independently scheduled by the GUI.

### GUI-API-04 — Threading, deadlines and backpressure

SDK transport has its own reader/dispatcher. GUI callbacks enqueue bounded typed updates onto the UI loop and return promptly. Rendering, audio decoding, slow filesystem work or waiting for a request result cannot block the IPC reader or GUI input loop.

Request correlation is not authorization. Known typed rejections, disconnection, cancellation and snapshot-unavailable results are handled immediately; do not await an impossible success until a generic timeout.

Coalesce replaceable state invalidations by scope/identity. Content-bearing events, accepted local capture and lifecycle results are not silently discarded. Use bounded durable-source catch-up where supported; otherwise surface overload, stop admitting new capture and preserve already accepted data. Section 20 defines baseline GUI budgets.

---

## 5. State lifetime, privacy and storage

### GUI-DATA-01 — Lifetime table

| State | Owner / location | Lifetime and cleanup |
| --- | --- | --- |
| DROP history, authorized outgoing DROP, unseen/pending LIVE, dedupe receipts | Core protected profile storage | Core contract only; GUI never cancels/deletes by navigation or cache eviction |
| Text drafts | GUI RAM, keyed by profile/peer/projection | Survive same-runtime navigation; discard on GUI restart, GUI exit, profile switch, hard lock and purge |
| Uncommitted GUI DROP Voice draft | Core-protected **owner-scoped staging**, GUI presentation in RAM | Disposable GUI-session policy in section 10; never automatically committed or restored as a user draft after owner loss |
| Authorized but interrupted outbound LIVE recording | Core | Preserve accepted prefix and finalize/recover according to explicit Core owner-loss policy; never sweep it as an unsent DROP draft |
| Consumed LIVE transcript / optional complete own-sent media copy | Bounded GUI volatile cache | Same runtime only; discard on hard lock, profile switch, exit/restart or purge; eviction removes corresponding replay/resend capability |
| Playback/scroll positions and context auto-play overrides | GUI RAM | Navigation/recovery may preserve within same logical context; true dismissal/runtime loss resets |
| Notification Center | Bounded profile-scoped RAM | Clear on hard lock, profile switch, restart, exit or purge; normal restricted lock retains only permitted sanitized presentation |
| Pins and peer-linked GUI preferences | Bounded protected profile GUI namespace through public host/SDK | Stable profile/peer identity; follows actual rename/delete/purge, never a global plaintext sidecar |
| Non-peer-linked platform preferences | Public local GUI/application settings | No secrets/content; do not copy profile metadata into device configuration |
| Device bindings | Explicit `device.toml` / registered adapter metadata | Read-only deployment configuration; no profile data; not destroyed by an ordinary profile purge |
| Password/PIN/proof material | Short-lived authorized auth path | No logs/settings/dumps by application design; release mutable buffers promptly; no persisted plaintext credentials |

### GUI-DATA-02 — GUI drafts are intentionally disposable

This version resolves the earlier conflicting draft proposals by retaining the original GUI product behavior: **GUI text drafts and uncommitted GUI DROP Voice drafts do not reappear after GUI owner loss.** Core may support recoverable drafts for other clients; that capability does not silently change this GUI policy.

Owner-qualified cleanup must be implemented through the public staging lifecycle. Hiding a draft is not deletion. Do not enumerate and cancel every draft in a profile. Section 10 specifies loss, temporary IPC interruption and committed/unknown-state handling.

### GUI-DATA-03 — Protected pin/preferences storage

Peer-linked GUI metadata is sensitive even without a message body. Persist only stable IDs and the minimal ordering/preferences required, not cached aliases, content previews or a second address book. Keep it under the selected profile's protection/deletion boundary using a bounded `ui.gui`-style public namespace. Exact accepted interface names are mapped in the integration document.

If protected storage is missing, add a narrow appropriate public service with tests. Do not silently downgrade to plaintext or represent a nonfunctional persistence promise as complete. Raw blob paths and encryption keys are never handed to a frontend for this purpose.

### GUI-DATA-04 — Lock and purge rendering hygiene

On restriction, immediately cover normal content, revoke normal input and stop unauthorized playback/capture while awaiting Core policy acknowledgment. Keep only the explicitly granted continued LIVE path active. Cached contacts/aliases/content cannot leak through accessibility labels, notifications, tooltips, window titles, clipboard or offscreen widgets.

On hard lock/profile change/purge, destroy GUI references to profile-owned sensitive state and cancel its pending jobs. Never claim physical secure erasure of every operating-system copy. Document deployment controls and actual test scope rather than overstating protection.

---

## 6. Startup, profile entry and first-run setup

### GUI-BOOT-01 — Entry states

The startup surface provides the configured default profile as the primary entry when one exists. Do not force a separate picker at every launch. Provide `Switch profile` and `New profile` without requiring an existing profile to be opened first.

If no profile exists, lead directly to the minimal encrypted-profile creation flow. If a configured default was removed, show profile selection rather than silently selecting another identity. A valid explicit launch profile takes precedence over the common default.

GUI profile creation uses supported public requirements and validates the name/password locally for presentation and authoritatively in the host/Core. It never reads or initializes SQL files itself. Production GUI does not offer plaintext-profile creation or plaintext-development switches; existing CLI development capabilities are not removed.

Cold or hard-locked encrypted profile activation requires the profile password. A PIN cannot start/decrypt it. Reattaching a new GUI client to a running profile follows normal full session authentication; it does not inherit the previous process's restricted authorization.

### GUI-BOOT-02 — First-run lock setup

After the first successful full-password entry for this profile and GUI installation, show one setup choice:

```text
Secure Metor
Set PIN
Use profile password
No screen lock
```

The default before completion is **Profile password**, not None. Leaving or interrupting setup preserves that conservative default. Store completion as protected profile-scoped GUI metadata. Removing a PIN or weakening the method requires appropriate full-password authorization; unlocking with a PIN is not by itself sufficient to change the root security policy.

This is Metor application/device access protection, not a claim to lock the desktop operating system. An explicit `None` choice requires a clear one-time warning and does not waive cold-profile password authentication.

### GUI-BOOT-03 — Loading, cancellation and unavailable state

Use compact states such as `Starting Metor…`, `Opening profile…` and `Loading…`. Normal messages avoid IPC/Tor/socket implementation language. Technical reasons remain in safe diagnostics.

Before authoritative bootstrap finishes, do not render stale profile content as current or enable communication actions. Failure offers a safe retry, profile selection or application exit as appropriate. Cancelling an auth/startup attempt cleans its resources and invalidates its callbacks. A failed target profile does not silently reopen an old profile.

---

## 7. Information architecture and view identity

### GUI-NAV-01 — Logical root

After successful full entry, root initially selects DROP. It exposes:

- the Metor identity/header role;
- Notifications, Contacts and Settings;
- the DROP/LIVE selector;
- the contextual new-conversation/new-LIVE action;
- the selected list and its current-state indicators.

These are semantic regions, not a pixel layout. The companion decides how they fit on the approved display without adding a Home screen or bottom navigation. A wide-screen arrangement may show equivalent regions together only if the approved layout preserves one explicit foreground communication context and the same action semantics.

Every pushed view has a discoverable Back affordance. Optional gestures/shortcuts are additional conveniences, not the only route. Returning from a peer preserves the originating DROP/LIVE root selection. Contacts/Settings/Notifications return to their calling view, or a safe root if that view no longer exists.

### GUI-NAV-02 — Required views and composite states

Use these stable IDs in layout deliverables, implementation traceability and tests. A view ID does not require a separate heavyweight page; several may be states/panels of one reusable component.

| ID | View / role | Required content/actions | Required variants |
| --- | --- | --- | --- |
| V01 | Boot / profile entry | Primary profile entry, password, Switch profile, New profile | Starting, no default, auth error, missing endpoint |
| V02 | Profile picker | Available permitted profiles, select, New profile, Back | Empty, many/long names, target unavailable |
| V03 | New profile | Minimal supported creation fields and confirmation | Validation, creating, failure |
| V04 | Lock-method setup/manage | PIN / password / None; appropriate credential confirmation | First run, change, forgotten PIN, failure |
| V05 | Restricted lock | Unlock; privacy-permitted call/activity; permitted continued LIVE indicator | PIN/password/None, cooldown, hidden name, Off/Anonymize/Show all |
| V06 | Root DROP | Relevant conversations, unread state, pins, contextual New | Empty, pending-only, anonymized, loading/error |
| V07 | Root LIVE | Active/recovering/unresolved LIVE contexts, contextual Start Live | Empty, active, recovering, pending/unseen, retained local context |
| V08 | Peer DROP | DROP items, composer, per-peer DROP/LIVE selector, contextual actions | Empty, text draft, recording, Voice review, sending, delete rejection |
| V09 | Peer LIVE | Ephemeral text/Voice, explicit lifecycle actions, composer, auto-play control | Idle, calling, active, recovering, disconnected, finalizing, quota/error |
| V10 | Incoming LIVE overlay | Decline, Accept, Open; request identity or opaque handle | Multiple requests, expiry, background, locked/anonymous/off |
| V11 | Contact picker | Intent-labelled saved-contact selection, Scan QR/manual entry | Start Drop, Start Live, already active, no contacts |
| V12 | Contacts | Saved Contacts only; add, My QR, contextual manage | Empty, search/filter as needed, long/anonymized transition labels |
| V13 | Add/save/rename contact | Supported contact data, local alias, intent-preserving confirmation | Existing peer, duplicate alias, invalid/self identity, denied save |
| V14 | Camera / QR input | Permission, scan/cancel, manual-data fallback | No camera, unreadable/unsupported QR, duplicate peer |
| V15 | My contact / identity | Own supported QR/address, optional allowed Copy | Loading, unavailable, new identity generation flow |
| V16 | Notification Center | Bounded sanitized entries, seen state, Dismiss, Clear | Empty, aggregated, stale targets, permission change |
| V17 | Settings | Flat Live/Privacy/Device/Profiles groupings and Advanced entry | Available/unavailable controls, validation, scoped changes |
| V18 | Activity history | Core projected metadata, clear | Empty, disabled retention, clear failure |
| V19 | Advanced diagnostics | Approved technical settings and explicit raw history | Unsupported capability, safe technical errors |
| V20 | Profile/identity management | Default/add/rename/remove/change password/change address | Confirmation, full auth, active profile restrictions, failure |
| V21 | Normal power/exit | Explicit action and local-safe preparation | Capture finalize, saving, retryable failure, close versus device shutdown |
| V22 | Purge | Physical arming feedback and authorized destruction result | Arming/cancel, accepted, irreversible-safe, cleanup failure, unknown |
| V23 | Startup/platform error | Truthful missing/invalid config, display/driver/capability failure | Before display, graphical error, supervised service failure |

Visual states for composer, playback, notifications and errors must be designed explicitly even when they are not separate view IDs.

### GUI-NAV-03 — Root DROP membership and pinning

Show only peers with actual relevant Core DROP state, not every saved contact. Creating a view or local draft alone does not create a conversation row. Unsent GUI Voice staging is not published conversation history.

Order pinned conversations first, then other conversations by canonical relevant DROP activity; use stable tie-breaking. Do not sort by a notification timestamp or arbitrary remote text. Keep pinned order deterministic; explicit Pin appends to the pinned ordering, Unpin returns to normal order. No drag-reorder feature is required.

Pin only DROP conversations. Rename and contact demotion preserve the stable peer-linked pin while a conversation remains. Remove a pin on an acknowledged conversation-clear action, even if pending delivery keeps the row relevant. Never re-pin automatically when delivery completes. A truly removed peer/conversation loses its pin. Do not create a pin-only ghost conversation.

Long-press/context menu: `Pin`/`Unpin`, `Delete conversation`. Deleting the conversation does not remove the saved contact or touch LIVE.

### GUI-NAV-04 — Root LIVE membership and lifetime

Show active, connecting/recovering and Core-unresolved disconnected contexts, including unseen inbound or pending outbound LIVE. Do not remove a context merely because its socket ended.

Within the current GUI runtime, a disconnected context may also remain while it holds a bounded, already-consumed local transcript. This is an explicit presentation-only retention: label it disconnected, do not fabricate Core pending/unseen state, and do not persist it. It can be closed locally when Core has no remaining state. On restart it is gone.

Order by active/recovering importance, then actionable pending/unseen state, then canonical recency with stable ties. No LIVE pins or user-configurable sorting system. Do not infer presence/online status beyond actual reported LIVE state.

A transport reconnect preserves the logical LIVE context and its in-runtime auto-play override. True dismissal ends that context. If the accepted contract cannot explicitly identify generations, the integration map must define an equivalent safe lifecycle boundary; never grant a new call an obsolete permission just because it uses the same Onion.

### GUI-NAV-05 — Entry intent and tab switching

Root DROP entry opens peer DROP. Root LIVE entry opens that existing LIVE context. A contact action `Start Drop` opens DROP. A contact action `Start Live` is an explicit call intent.

Tapping the peer LIVE tab always opens LIVE **without** placing a call. If no connection/context exists, offer `Start Live`. For an ended context, offer `Reconnect` where allowed. If active or genuinely recovering, show the existing state; do not start a second attempt. Tapping DROP leaves any LIVE connection active.

Do not remember a last-used peer tab in a way that defeats the explicit entry intent. Changing view can cause the PTT finalization/re-arm behavior in section 9, but not an implicit disconnect/fallback.

---

## 8. Explicit communication and incoming-call flows

### GUI-ACT-01 — Stable action vocabulary

Use these action IDs in the future layout, even if the exact final visible copy changes.

| Action ID | Meaning | Eligibility / side effects |
| --- | --- | --- |
| A01 OPEN_DROP | Open DROP view | Navigation only |
| A02 OPEN_LIVE | Open LIVE view | Navigation only |
| A03 START_LIVE | Explicitly initiate a new LIVE request | Correct peer, authenticated capability, no conflicting existing attempt |
| A04 RECONNECT | Explicit reconnect of ended context | Reported eligible state, not a second recovery worker |
| A05 ACCEPT | Accept pending call and remain in current view | Valid request/handle and authorized policy |
| A06 DECLINE | Reject pending call | Exact current request/handle; no view switch |
| A07 OPEN_CALL | Authenticate if necessary, accept if pending, open that LIVE | Revalidate after auth; never call back an expired request automatically |
| A08 END_LIVE | Explicitly end LIVE | Core decides preservation/fallback; no discard-pending option |
| A09 CHANGE_ROUTE | Request route change in active eligible LIVE | Typed outcome; no destruction of context/transcript |
| A10 CLOSE_LIVE | Dismiss eligible disconnected context | Core must reject if pending outbound or active/recovering work remains |
| A11 SEND_TEXT | Send text under displayed DROP or LIVE semantics | Explicit send; retain draft on rejected/unknown operation |
| A12 PTT | One hold, one bound Voice turn | Input eligibility, media limits, finalization/re-arm rules |
| A13 PLAY_VOICE | Explicit playback | Available authorized content and output capability |
| A14 SEND_DRAFT | Commit finalized DROP Voice draft | Exact owner/target; explicit user send only |
| A15 DELETE_DRAFT | Cancel this GUI's unsent DROP draft | Never an already committed delivery-critical item |
| A16 FALLBACK_SELECTED | Convert selected pending LIVE to DROP | Exact eligible IDs, same identity, atomic Core result |
| A17 FALLBACK_ALL | Convert eligible pending LIVE items for peer | Core eligibility; active incomplete recordings are not silently converted |
| A18 RESEND_DROP | New DROP from available own delivered LIVE content | New ID; never a copy of received LIVE in V1 |
| A19 DELETE_DROP | Delete one eligible local DROP item | Direction-qualified identity, no remote delete or send cancellation |
| A20 CLEAR_DROP | Clear eligible DROP conversation state | Pending delivery may remain; no LIVE effect |
| A21 LOCK_APP | Restrict this authenticated GUI | Does not hard-lock every client or the desktop OS |
| A22 SWITCH_PROFILE | Explicit safe runtime transition | Core/host authorization and phase-aware result |
| A23 EXIT_GUI | Close/detach this GUI | Own capture/drafts cleanup; no implicit host power-off |
| A24 POWER_OFF | Explicit supported appliance shutdown | Authorized local safe profile exit first |
| A25 PURGE | Authorized emergency selected-profile destruction | Configured physical chord, preauthorized capability, truthful milestones |

Disable actions while their exact operation is pending. Debounce repeat activation using operation identity, not a timer that can still enqueue duplicates. On uncertain delivery, reconcile the same ID; do not generate a second send ID merely because a request timed out.

### GUI-FLOW-01 — Root contextual new action

DROP New: show an intent-labelled saved-contact picker or Scan QR/manual entry. Selecting a saved contact opens DROP. For a new peer, final confirmation says `Save & Open Drop` and preserves that intent. Do not make the user find the contact again.

LIVE New: show a clearly labelled `Start Live` picker. Selecting a saved peer is the explicit start action and initiates exactly one request; if already active/recovering, open that existing context. A newly scanned peer uses `Save & Start Live`. No extra Start confirmation after that labelled action.

Contact-add from the Contacts view only saves; it does not start DROP/LIVE. A failed contact save never proceeds to call. Cancelling before the intent-labelled confirmation has no call side effect.

### GUI-FLOW-02 — Incoming LIVE overlay

Incoming requests are globally presentable subject to the active lock/privacy policy. The overlay preserves the underlying screen and drafts.

`Decline`: reject, remain in place. `Accept`: accept, remain in place, no automatic foreground/PTT/auto-play promotion. `Open`: obtain normal GUI access if needed, revalidate, accept if still pending, then navigate to peer LIVE.

Multiple pending requests need separately addressable entries; do not let a newer request overwrite the selected action target. Expiry, cancellation or another client's action updates the overlay idempotently. An expired `Open` does not place a new outgoing call. If the same request has already been accepted and its permitted current context is known, Open may navigate without another accept.

Normal and anonymized forms expose the same meaningful choices. Anonymous actions use opaque Core-issued request handles. On `Accept` denied by locked policy, offer normal unlock before accepting and leave a valid Decline route. Never infer a caller's saved-contact status through an unauthorized lookup or leaked refusal text.

### GUI-FLOW-03 — Lifecycle UI

Calling shows a clear cancellable state. Cancel uses the Core's exact pending-attempt cancellation/end operation; it cannot cancel a later replacement call accidentally.

`Change route` is a secondary action inside eligible active LIVE. Use `Changing route…`, then brief truthful success/failure. Do not show route IDs or expose transport selection. Recovery and already buffered messages remain in the same logical context.

`End Live` is available from peer LIVE and root LIVE contextual actions. Ordinary end does not require a redundant confirmation; when pending consequences need attention, show them without inventing a discard operation. Respect the actual fallback setting. Do not always force DROP merely because an earlier design example used a fallback pending policy.

`Close Live` is for an ended, non-recovering context. Pending outbound LIVE prevents dismissal. Tell the user to reconnect or send pending as DROP. A local-only consumed transcript can be removed without a network command when Core reports no remaining context state; no hidden payload survives that local close.

---

## 9. Text composer and PTT state machine

### GUI-INPUT-01 — Text entry

DROP and LIVE have separate text-draft keys per peer. Drafts survive same-runtime navigation but are never persisted. Normal explicit Send uses the displayed delivery semantics. Do not reinterpret a typed LIVE send as a GUI-authored DROP without the Core's authoritative fallback outcome.

LIVE new-text/PTT actions are available when active or genuinely recovering. A terminally disconnected LIVE view offers Reconnect and pending fallback, not arbitrary new LIVE sends. Core remains the final eligibility check if state changes between rendering and activation.

On local send rejection, preserve the draft and explain the outcome. On unknown outcome, reconcile the same message identity before allowing a retry that could duplicate it. Clear the draft only on confirmed local acceptance, not on a remote-delivery assumption.

### GUI-INPUT-02 — Software and desktop keyboards

The local software keyboard supports QWERTY and QWERTZ, numbers and necessary special characters, without cloud suggestions, telemetry or a learned persistent personal dictionary. No network-fetched input assets. Autocorrect is not required.

Touch/device mode shows it for a focused text/password/PIN field where appropriate. Desktop uses the physical keyboard by default and provides an explicit way to show the software keyboard. Secure input is masked, never echoed into logs or the ordinary composer, and not subject to clipboard/history conveniences.

The keyboard hides during PTT, DROP Voice review, explicit dismissal or leaving the field/view. After LIVE PTT ends the normal composer becomes available again, but do not force keyboard visibility after the user dismissed it. After DROP Voice review, text mode returns on Send/Delete.

### GUI-INPUT-03 — One source owner, one press, one target

Normalize physical-button, on-screen pointer and optional focused-key events into one semantic PTT controller. On valid PTT-down, bind profile, peer, delivery, GUI activation generation and, for LIVE, permitted context generation. One active local recording at a time per GUI instance. One press produces one logical message ID, not one per chunk.

Autorepeat and duplicate down events do not start additional recordings. Only the owning input release/cancel ends the press. A second input source cannot retarget or steal it. State transitions are explicit:

| Current state | Event | Result |
| --- | --- | --- |
| Idle | Eligible PTT-down, no conflicting review draft | Begin one bound turn; enter Recording only after local admission |
| Idle | Not eligible / no microphone / quota full | Explain or disable, no fabricated recording |
| Recording | PTT-up | Stop capture, submit remaining accepted complete frames, await local finalization |
| Recording | Context departure / application focus loss / forbidden lock | Stop and finalize the bound turn, then navigate/lock safely; Release-required if physical release not observed |
| Recording | Genuine LIVE recovery | Same turn may continue while authorization/quota permits; no identity change |
| Recording | Hard/refusal boundary | Stop capture, finalize accepted codec-valid prefix once; Release-required |
| Recording | Authorized purge acceptance | Abort normal capture path; no finalization-for-delivery or fallback |
| Finalizing | Completion | LIVE returns to composer; DROP enters review; preserve input-release barrier |
| Finalizing | Local persistence/operation failure | Truthful preserved/retryable error; no success/send claim |
| Release-required | All relevant held inputs released | Return Idle, or blocked-by-capacity if capacity is still unavailable |
| Blocked-by-capacity | Capacity returns and press is released | Re-enable start, never auto-start |

Network loss does not synthetically release PTT. A terminal loss of the authorized locked LIVE context does revoke its permission and must stop new locked capture. Section 14 defines this boundary.

### GUI-INPUT-04 — Context changes

Leaving Alice LIVE for Bob LIVE, Alice DROP, Back, Contacts, Settings, Notifications or Open on Bob's call finalizes Alice's current recording and cannot start Bob while the button remains held. `Release PTT` is the minimal hint.

Accepting Bob while remaining on Alice does not finalize Alice or change the target. An explicitly permitted same-context lock may preserve Alice capture. DROP capture departure finalizes to an **unsent** review draft for its original peer, not to an outgoing message.

Focus loss, pointer-capture loss, input-device unplug, OS lock/suspend and a missing release event must not leave a stuck recording. Apply the safe stop/finalize and re-arm rule; never infer a new down event on resume. Bound asynchronous finalization and do not block the GUI loop waiting for it.

### GUI-INPUT-05 — Full duplex and composer exclusivity

Core and audio transport remain full duplex. During this GUI's own PTT, incoming text/Voice and eligible playback remain functional and visible. Another authenticated client is not restricted from sending text.

The **same GUI's local text composer is intentionally unavailable while its recording UI is active**. This resolves the old contradictory simultaneous-text wording. Do not freeze the timeline or replace it with a full-screen recording modal. After release/finalization, restore normal text interaction.

At PTT admission, create one stable chronological placeholder. Incoming text may appear below it while recording. Finalization updates the same item in place; do not move/reinsert it at the release timestamp.

---

## 10. Voice capture, DROP review and draft ownership

### GUI-VOICE-01 — DROP and LIVE differ at release

DROP PTT records a local unsent draft. Release finalizes it but never commits it. Review offers `Play`, `Delete`, `Send`. Play does not consume/send/delete the draft. Delete cancels that exact unsent owner-qualified draft. Send explicitly commits it to DROP using its existing draft ID.

LIVE PTT streams under its bound identity and finalizes on release; there is no review step. Core retains/retries/fallbacks the authorized content under its own policy. GUI does not implement a second replay loop or expose chunking to users.

An ID can be allocated by the GUI through the public SDK as part of starting a logical action. Core owns validation and acceptance of that identity; it is not created again on every retry.

### GUI-VOICE-02 — Review, navigation and multiple drafts

At most one uncommitted DROP Voice draft per `(GUI owner, profile, peer)` may be in recording/review. A new PTT-down while that peer's review exists must not overwrite it; show `Send or delete this recording first`. Other peers may retain their own same-runtime review drafts subject to declared aggregate bounds.

Navigation preserves the review in the current GUI runtime, still bound to its original peer. It is not a root conversation until committed. Returning restores review. Leaving while recording stops/finalizes to that peer's review and consumes the press until release.

A Core resource-limit finalization enters DROP review, never auto-Send. A failed commit leaves a review or explicit unknown-outcome state. Reconcile the exact ID before enabling another Send. An empty or invalid media result is a failed/cancelled capture, not a falsely playable message.

### GUI-VOICE-03 — Disposable GUI staging over recoverable Core primitives

Before beginning a GUI DROP draft, establish a public owner/session token with a disposable-staging policy. It is distinct from the generic Core facility for recoverable drafts used by other clients. Core staging is protected and may be crash-safe internally; that does not make it permanent GUI draft history.

For a normal GUI close, profile switch or hard profile lock, explicitly cancel all and only this GUI owner's uncommitted DROP drafts. Normal restricted screen lock alone does not cancel them; they remain inaccessible behind restriction.

For GUI-process loss, confirmed owner-session loss, or daemon restart invalidating that owner, Core/host cleanup reclaims only the declared disposable uncommitted staging. A fresh GUI does not restore it as a draft. Cleanup failures remain tracked and retryable by the appropriate owner, not silently forgotten. The GUI cannot safely implement this merely by clearing RAM or by saving a global list of blob paths.

A short IPC interruption that the SDK transparently recovers within the same valid owner lease does not delete staging. Once Core invalidates the owner, a reconnect cannot assert the old identity locally; require fresh authentication and display that unsent drafts were not restored, without storing their content/peer list to explain it.

Commit transfers the item out of disposable draft ownership. Unknown commit outcomes require identity/state reconciliation; an owner cleanup must not cancel an item that actually reached the authorized outgoing queue. Other clients' recoverable drafts are neither shown as this GUI's own draft nor automatically cancelled.

If the accepted refactor lacks owner-scoped disposable staging, this is an explicit narrow integration dependency, not permission to sweep all profile drafts or quietly switch to persistent GUI drafts. Record and implement/test it in the proper public host/Core owner before declaring this behavior complete.

### GUI-VOICE-04 — Interrupted authorized LIVE capture

LIVE capture becomes delivery-authorized at Begin and is not an unsent DROP draft. GUI loss must not cause a generic draft-cleanup sweep to erase its already accepted bytes.

Use the Core's typed interrupted-capture/owner-loss contract to freeze and finalize the accepted codec-valid prefix or retain an explicit recoverable interrupted item. It must never wait forever for a vanished producer. Finalization/recovery failure remains visible as preserved pending state. On reattach, inventory provides its identity and permitted next action; do not silently turn it into a new message or resume the microphone automatically.

This may require a narrowly scoped producer-lifecycle hook if the public contract does not already provide one. Purge remains a separate preemption path and never runs normal capture finalization-for-delivery.

### GUI-VOICE-05 — Capture backpressure and limits

Respect all effective Core limits; a larger LIVE Voice budget does not override a smaller total pending-LIVE budget. GUI transient buffers have their own lower/equal finite bounds. No user-facing segment-duration setting and no automatic new logical message at a quota boundary.

At Core pressure near its declared warning threshold, show `Voice buffer almost full`. At hard/refusal boundary, stop capture, finalize only the accepted complete codec-valid prefix and enter Release-required. Do not slice an encoded packet to make a byte limit fit, ACK rejected bytes, overwrite retained audio, or label an unaccepted frame as sent.

Use the typed limiting resource for action text. Pending-LIVE pressure may suggest Reconnect or Send pending as Drop. Unsent DROP staging pressure suggests Send/Delete the owner's review drafts. GUI playback-cache pressure suggests stopping/finishing playback or releasing volatile copies, not falsely claiming that fallback always frees every kind of buffer.

Existing pending/unseen data is never deleted to lower a limit. A full buffer disables new PTT until both capacity and a fresh physical press are available. Capture/device errors preserve admitted content and explain the actual failure without promising full remote delivery.

---

## 11. Voice playback, auto-play, timeshift and consumption

### GUI-AUDIO-01 — Playback inputs and identity

Discover retained items through the non-consuming public inventory; obtain bytes only via authorized bounded SDK reads/events. A new GUI must not need pre-known IDs or private blob paths. Decode only a declared supported codec/container, validate incremental framing and avoid arbitrary native-code/plugin selection from peer metadata.

Codec packets, transport chunks, file-byte offsets and playback time are distinct. The platform ADR defines the canonical supported wire-media framing and decoder seek checkpoints. Do not assume a random byte offset is a valid audio start point. A jump must use a safe decoder boundary and bounded look-back/indexed access, not replay the whole recording on every small read.

### GUI-AUDIO-02 — Foreground and auto-play eligibility

Effective auto-play requires all of:

- current authenticated/authorized GUI activation;
- the selected peer LIVE view is foreground, or its exact context has an explicitly granted locked-continuation capability;
- that context's auto-play preference is On;
- functioning output/routing and a valid media stream;
- no manual playback taking output priority.

The global auto-play default is **Off**. A new logical LIVE context copies it into a volatile override. The override persists across view switches and genuine recovery of that context; it resets on true dismissal or GUI-runtime loss. A global preference change applies to future contexts, not silently to existing overrides.

Outside foreground, audio never auto-plays. Returning to a peer or unlocking never plays old backlog automatically. For a turn already in progress when eligibility begins, V1 requires manual Play or explicit LIVE jump; only a newly beginning incoming turn after eligibility is established may auto-start. This rule prevents partial old audio from unexpectedly sounding during navigation.

A normal desktop window losing foreground focus revokes ordinary auto-play eligibility. OS/application lock follows section 14; it is not secretly treated as foreground. The only background exception is the exact explicitly continued locked LIVE context.

### GUI-AUDIO-03 — Output arbitration

One audible playback stream at a time per GUI instance. Capture and that output may run simultaneously. Do not mix different peers or automatically promote a background peer.

Manual Play takes priority over auto-play; newly arriving items while manual playback owns output remain new/unseen rather than interrupting it. When manual playback ends, do not retroactively play that backlog. Subsequent newly arriving eligible turns may auto-start.

Multiple eligible incoming turns from the same peer are processed in stable order through a bounded queue. Capacity/eligibility loss leaves content in Core for later explicit playback and shows new state; it is not silently consumed. Switching context stops the previous output promptly and does not automatically resume it on return.

### GUI-AUDIO-04 — Manual playback and live edge

Tap a completed Voice item to play from its beginning. Tap an arriving item to play from the earliest retained decodable beginning. While behind the current arriving edge, offer a compact `LIVE` jump. It advances to the newest safe decoder position; never promise zero network/codec delay.

Manual playback may coexist with typing when PTT is not held, or with PTT capture while the local composer is in recording mode. Incoming content stays visible in either case.

If data is not yet available, show a truthful buffering state. If a missing portion cannot be recovered, show an incomplete/unavailable result rather than synthetic silence labelled as complete. Pausing, seeking and leaving the view do not create a persistent listening history.

### GUI-AUDIO-05 — Explicit consumption and safe release

A placeholder, list visibility, unread-count query or byte download does not consume Voice. Use the accepted public handoff/release operation, not text-only bulk MarkRead.

For this GUI, release/mark a finalized inbound Voice item consumed only after its complete accepted content has been safely handled by playback under the Core handoff contract. Track local playback coverage while the GUI is alive. A jump over unheard content does not fabricate full listening coverage; retain the unresolved Core item until later playback or explicit eligible discard/dismiss. Playback completion is an application handoff fact, not proof a human heard or understood sound.

Do not release incomplete/unfinalized Voice just because the current playback cursor reached the available edge. Do not consume a background peer when its count or placeholder updates. Enforce the exact restricted-target scope when reading/releasing permitted locked LIVE media.

A successful release may shred Core LIVE payload or ephemeral DROP payload according to Core policy. The GUI may retain a bounded volatile copy for same-runtime replay only where allowed. If that copy is evicted, do not fetch/reconstruct erased Core content or maintain a hidden disk recording.

Actual remote READ emission belongs to Core and is optional. It follows the accepted consume operation and local setting, not GUI heuristics or the delivery ACK. A bounded safe handoff contract must not be weakened simply to make a Read indicator appear earlier.

### GUI-AUDIO-06 — Timeline and scroll anchoring

Auto-scroll only while the user is already at the LIVE edge. Scrolling upward or manually playing an older item suppresses forced scroll. Show a bounded `N new` affordance; tapping it restores the timeline edge without starting a call or marking hidden Voice played.

Media arrival/ACK/retry updates an existing stable item. A Voice placeholder does not move after finalization. Deduplicate by message identity, not by timestamp or displayed text. Large histories/inventories are paginated/virtualized; do not load every recording to populate a list.

---

## 12. Recovery, fallback, deletion and message status

### GUI-MSG-01 — Recovering versus ended

During genuine reported recovery, keep the context, transcript, auto-play override and permitted recording identity. Show `Reconnecting…` without exposing transport internals. New admitted LIVE content can be pending under Core limits.

After terminal end, preserve relevant pending/unseen or current-runtime local transcript state. Show Reconnect and eligible pending fallback. Do not reconnect because this view was opened or because the user unlocked. If another client resolves that state, reconcile and remove stale actions.

For a local safety overflow, present the typed local system reason, for example `Unread Live limit reached`. On the remote side, present only the generic end reason actually reported; never claim knowledge of the other peer's quotas. Ordinary idle timeout, peer end and local user end use their actual typed actor/reason.

### GUI-MSG-02 — Selected and bulk pending fallback

`Send as Drop` on an own pending LIVE item invokes exact selective fallback. `Send N as Drop` invokes the eligible bulk operation. Preserve profile, peer, direction and IDs. No receipt reconstruction or GUI replay cancellation substitutes for a Core transaction.

Incomplete current recordings are not eligible for mid-turn fallback. Disable the individual action while recording/finalizing. Bulk presentation uses Core-reported eligible items/counts and cannot falsely promise that an unfinalized turn was converted. When the operation races with ACK/replay or another client's action, apply the typed atomic result and refreshed state; do not retry a partially changed selection under a new identity.

Feedback describes local conversion, for example:

```text
3 Live messages queued as Drops
```

Do not say `delivered` or `sent as Drops` merely because fallback committed locally. Converted content appears in DROP according to Core's projection and is removed from LIVE replay/pending eligibility; an in-runtime LIVE visual marker may show the transition without creating a second logical message.

Fallback Off means unresolved pending content remains. No forced modal, TTL, automatic conversion or discard-pending action. Core's current policy governs explicit End Live, graceful profile exit and later recovery.

### GUI-MSG-03 — Delivered own LIVE resend

For an own already delivered LIVE item, `Resend as Drop` means a **new** message. Offer it only if the complete permitted source content remains available in this GUI's bounded current-runtime cache or an explicitly permitted public source.

For Voice, create a new DROP staging item with a new ID from the complete encoded source, finalize and explicitly commit it as the requested resend. The user action itself is Send intent; do not manufacture an old LIVE retry. For text, send a new DROP with a new ID. Do not offer this for received LIVE items in V1.

Eviction, hard lock, profile switch, restart or unavailable source removes the action or explains unavailability. Do not create persistent shadow LIVE history to keep Resend permanently available. A failed/unknown resend reconciles its new ID, not the original LIVE identity.

### GUI-MSG-04 — Local clear/delete

Single DROP delete is local-only and direction-qualified. Pending delivery-critical DROP is not cancelled by Delete. Disable/explain an ineligible action or show its typed rejection; do not optimistically remove an item permanently before successful reconciliation.

Conversation clear and Clear all conversations mean DROP-only. They never erase LIVE, disconnect, fallback or remove contacts. A confirmed clear may preserve pending outgoing DROP and therefore leave a relevant row. Explain `Queued messages are not cancelled` when that distinction matters. Do not promise that the row must vanish.

Actual deletion removes eligible local content and only the Core-permitted metadata. No remote delete protocol, Delete for everyone, message quoting, reactions or forwarding.

### GUI-MSG-05 — Text handoff and read receipts

Use the accepted delivery-filtered text handoff/consume path only for the intended foreground peer projection. Opening LIVE cannot consume DROP, and vice versa. Where a public operation atomically returns and consumes a text batch, treat all returned payloads as a protected foreground handoff: bounded admission, reliable handling, no blanket revision discard. Do not consume arbitrary background batches to fetch an unread count.

Voice uses its separate inventory/read/release contract; a text-only MarkRead result does not release Voice. Local consumption is distinct from peer delivery and from human comprehension.

`Send read receipts` defaults Off in Core and controls **local emission**. Receiving an actual valid peer read receipt may be displayed even when local emission is Off. Absence of a receipt means unknown, not `Unread`. Use minimal truthful states: preparing, locally queued/pending, action-required failure, and optionally subtle confirmed delivered/read. Do not fabricate multi-checkmark semantics without evidence.

---

## 13. Notifications and volatile Notification Center

### GUI-NOTIFY-01 — No previews anywhere

Never put message text, Voice bytes, transcript extracts or body previews into toast/banner, lock view, Notification Center, desktop system notification, device indicator text or detached sink metadata.

Allowed example: `Alice — New Drop`. Disallowed: a quoted line from Alice's message. Render local aliases as plain text without executable markup; use safe length/character handling even for user-supplied labels.

### GUI-NOTIFY-02 — Model and bounds

Use a typed, bounded, profile-scoped volatile entry model: kind, permitted peer/action reference, count, local display timestamp, actionable-versus-info classification, seen state and source state identity/revision. No arbitrary remote `details` bag.

State entries represent current actionable Core facts, such as a pending request or disconnected context with pending content. Resolve/update them when the fact changes. Info entries represent bounded transient observations, such as a successful local fallback, and may disappear on seen/dismiss/eviction.

Coalesce low-value churn by permitted kind/peer and a small bounded time window, for example `Connection unstable`. Do not aggregate away current requests, pending actions or security/power failures. Section 20 gives count and byte budgets; actionable truth remains recoverable from Core even if an info entry is evicted.

### GUI-NOTIFY-03 — Interactions

Opening the center marks presented entries seen, not messages consumed. Tap navigates to current permitted context: DROP for new DROP, LIVE for relevant LIVE. It does not reconnect or accept unless the UI explicitly presents the corresponding call action.

`Dismiss` removes the presentation entry. `Clear` removes center entries only: no message/history deletion, fallback or Core LIVE dismissal. Use a volatile source-state watermark so clearing a state entry does not instantly recreate the same notification on an unchanged snapshot; a genuinely new state generation may create a new entry. Root unread/pending indicators still reflect Core.

Stale targets are reconciled or discarded gracefully. Do not navigate to a deleted peer, display a stale count as current, or infer a new call from an expired notification.

### GUI-NOTIFY-04 — Locked privacy modes

| Mode | Permitted locked presentation |
| --- | --- |
| Show all | Authorized alias/identity and event kind, but never body previews |
| Anonymize | Event kind and allowed aggregate/action handle only; no alias, generated anonymous alias, Onion, saved status or indirect identity hint |
| Off | No unsolicited call UI, banner, activity text, badge, display wake or notification LED/haptic |

Default is **Anonymize**. Privacy applies to the entire restricted presentation path, including accessibility text and queued notifications generated before lock. Do not keep a second unrestricted subscriber merely to populate a locked Notification Center.

Off does not disable Core's independent authorized auto-accept/background reception policy. It also does not revoke the separately explicit continued locked LIVE permission: its permitted audio/PTT and non-identifying active-media safety indication may continue. Unrelated activity stays hidden.

### GUI-NOTIFY-05 — After unlock

Refresh current unread/pending state after reauthorization. An exact `N notifications while locked` banner is allowed only from actually received privacy-permitted bounded volatile facts. If Off withheld the events, do not invent an exact historical count from current unread totals or rebuild a notification log from Core history.

A permitted generic missed-activity banner navigates to the center/current state. It is not persisted. The absence of a banner is acceptable when no truthful count is available.

---

## 14. Application/device lock, PIN and locked LIVE

### GUI-LOCK-01 — Restrict this client, not the profile runtime

Normal Power-short-press, application Lock or configured idle timeout enters per-client restricted lock. The daemon and other authenticated clients remain active. Do **not** call hard Core `LockCommand` for normal screen/application lock.

Request restriction with the previously authenticated settings and current exact permitted LIVE context. The Core grants/fixes a policy for that lock cycle. The GUI immediately covers private content and disables normal access; it does not leave a visible unlocked window while waiting for acknowledgment.

If restriction cannot be confirmed, remain covered, stop privileged continuation, disconnect/reauthenticate as required and show a safe reconnect/unlock surface. Never present an unconfirmed client-side boolean as an enforced lock. Do not open a replacement unrestricted IPC connection behind the lock.

### GUI-LOCK-02 — Unlock methods

| Method | Normal restricted GUI access | Cold / new-client / hard-locked profile |
| --- | --- | --- |
| PIN | One-use proof through Core, subject to three-attempt escalation/cooldown | Not sufficient |
| Profile password | Normal profile-password proof through Core | Required according to public full-auth flow |
| None | Explicit Core-sanctioned immediate reauthorization for this same valid restricted session | Does not bypass profile password/new-client authentication |

Core, never GUI, validates PIN/password and maintains failure/cooldown state. The GUI mirrors typed remaining/retry outcomes, not independent counters that can reset server policy.

`Forgot PIN?` requests a fresh normal password challenge; it is not implemented by intentionally sending a wrong PIN. Three wrong PIN attempts disable PIN for that lock cycle; successful password recovery restores next-cycle eligibility. No automatic purge. Stale/replayed challenges and auth results from old profile/connection generations are rejected/ignored.

PIN change/remove and weakening security require the full authorization strength specified by Core. A PIN-reauthorized UI must not change a PIN/verifier or root credentials merely because it is visually unlocked. No secret/derived credential in general settings.

### GUI-LOCK-03 — Continued locked LIVE

`Keep Live active while locked` is a presentation/limited-interaction option, default **Off**. Its label does not imply that turning it Off disconnects background LIVE connections. It determines whether one foreground LIVE context can retain audio/PTT privilege while locked.

If enabled while locking from a permitted active/genuinely recovering peer LIVE view, Core may grant continuation for that exact context generation. The existing per-context auto-play override still applies. With auto-play Off, inbound media remains silent. All other peers remain background/unseen and cannot inherit the target.

Locking from DROP, root, Contacts, Settings or Notifications grants no continued foreground target. Accepting a call while locked does not create one. An application-lock action never silently promotes the most recently active peer.

A temporary transport interruption in the same Core-authorized recovering logical context may preserve continuation. A **terminally ended/revoked context** loses the permission even if a later call uses the same Onion. Stop new PTT and unauthorized playback, finalize an already authorized capture through the allowed Core path where appropriate, and require release before re-arm. No local extension of an expired capability.

### GUI-LOCK-04 — Locked calls: three independent policies

1. `Auto-accept Live from saved contacts` is normal Core behavior, default false.
2. `Accept Live while locked` controls manual Accept without opening the normal GUI: All / Saved contacts / None, default None.
3. `Auto-play` controls output only for the eligible foreground/continued context, default Off.

Do not merge them. With locked notifications Off, there is no unsolicited call overlay even if Core auto-accepts. With Anonymize, action authorization is decided by Core using the current opaque handle without leaking caller identity/classification.

Decline is permitted only through the current allowed request handle. Accept denied by locked policy invokes the configured normal unlock path before retrying the same still-pending action; it does not force a special stronger password just for Accept/Open. Open always restores normal GUI access, then revalidates request state and navigates.

### GUI-LOCK-05 — Profile name, focus, screen and OS events

`Show profile name on lock screen` defaults Off. Hide the active profile name from the lock landing view, window title and accessibility surfaces when Off. Do not leak it in an auth error or ordinary notification.

In an already running restricted GUI, switching to a profile-management/list view first requires normal GUI reauthorization; it is not a back door into the previous profile. At cold startup, the explicit profile chooser may display the permitted local profile inventory needed for selection. The hide-name setting is not a promise to conceal that inventory from someone with host filesystem access.

The idle timer measures user inactivity, not message arrival. Valid ongoing deliberate PTT interaction prevents accidental idle timeout; explicit Lock/Power still applies. Default application idle timeout is 120 seconds. Device screen blanking uses the configured adapter; desktop application lock covers only Metor. Do not claim to lock or power down the OS by covering the app.

On OS lock/suspend, revoke ordinary foreground eligibility, stop unsafe capture and apply restriction. On resume, validate transport/auth generations before revealing content. Never auto-start a microphone or use an unseen key-up/down reconstruction to continue a press.

---

## 15. Contacts, QR, identity and activity history

### GUI-CONTACT-01 — Saved Contacts only

Contacts contains Saved Contacts, not a top-level Discovered address book. Provide add, My QR and contextual Start Drop, Start Live, Rename and Remove contact. A plain contact activation may open its available actions/details as specified in layout; it never places an unlabelled call.

Discoverable/anonymized peers appear in DROP/LIVE only while relevant state exists, using the current Core-provided alias. Their contextual `Save contact` promotes them through Core with a local alias.

### GUI-CONTACT-02 — Rename and demotion

Rename changes labels everywhere while stable peer identity, pins and active communication remain intact. Resolve successful operations through actual Core results, not optimistic renaming of a partial set of widgets.

Remove contact requires clear confirmation and uses Core deletion/demotion semantics. It does not necessarily disconnect or erase communication. On demotion, remove the saved-contact row, apply the current anonymous alias to relevant contexts, and remove the old human alias from notifications, offscreen caches, accessibility text and in-flight presentation jobs. A generic `Contact removed; active communication continues` notice avoids retaining the old alias in a new history entry.

Clear all contacts is a confirmed Contacts/Manage action using the same demotion rules. Do not fake-delete referenced peers or preserve a hidden old address book in GUI preferences.

### GUI-CONTACT-03 — QR flows and intent

Use only the accepted Core/host contact encoding/validation format; do not invent a competing unversioned QR protocol. The QR contains supported contact identity data, not profile passwords, secret keys, a forced local alias or active commands.

Scan is an explicit camera action. Bound image/decode input, release camera promptly, validate before saving and render safe plain text only. Unsupported/self/malformed identities and duplicate aliases are explicit outcomes. A scanned payload cannot execute code, automatically load a URL or invoke a shell operation.

Contacts Add -> validate/alias -> Save only. DROP New -> validate/alias -> Save & Open Drop. LIVE New -> validate/alias -> Save & Start Live. Existing saved/discovered identity uses its canonical Core identity; no duplicate contact or duplicate ring is created. No-camera manual entry follows the same validation/intent steps.

### GUI-CONTACT-04 — My contact and address regeneration

My QR shows the permitted own address and supported QR format, with Copy only when clipboard policy allows. It is an everyday Contacts action.

`Generate new address` is under Profiles/Identity settings, with an explicit explanation and confirmation. Use Core's actual preconditions and effects. Do not imply old conversations or contacts will magically follow a rotated address. Do not run it as a navigation side effect or expose it on the lock view.

### GUI-HISTORY-01 — Message history is not activity history

DROP message history remains inside the peer DROP conversation. LIVE is not persistent chat history. Activity history in Settings shows the Core's projected user-facing metadata only; it is not a substitute transcript or Notification Center export.

`Record Live history`, `Record Drop history` and `Ephemeral Drops` retain their Core meaning. Disabling activity recording does not invite the GUI to keep a replacement event database.

Raw transport history is an explicitly technical Advanced/Diagnostics view. It may show documented technical metadata, not hidden message previews. `Clear activity history` invokes the exact approved Core history-clear scope, including its documented underlying ledger effects; do not claim it clears only a cosmetic projection while secretly retaining a recreatable hidden copy.

---

## 16. Settings, scopes and defaults

### GUI-SET-01 — Mostly flat settings

Use ordinary user concepts, not code ownership labels. Primary visual groups are Live, Privacy, Device and Profiles. Advanced is the intentionally deeper technical area. Device/Profiles groups may combine subflows where forms genuinely require them; avoid turning each individual toggle into its own page.

Show supported settings only. A disabled control explains unavailability when its absence would confuse the user. Core descriptors determine value types, constraints, scope, effective source and permitted deployment use. GUI does not copy Core defaults into an independent authoritative policy store.

### GUI-SET-02 — Semantic mapping

| Group | Visible capabilities | Owner / notes |
| --- | --- | --- |
| Live | Auto-play default; Fallback to Drop; Receive Drops; Auto-accept Live from saved contacts; Keep Live active while locked; Accept Live while locked; Send read receipts | Core delivery/acceptance/receipt settings remain Core-owned; GUI preferences become fixed Core-enforced policy at restriction |
| Privacy | Ephemeral Drops; Record Live history; Record Drop history; Lock screen notifications; Activity history; Clear activity history; confirmed Clear all conversations | No previews; all-conversations action is DROP-only |
| Device | Screen/application timeout; Unlock method; Change/Remove PIN when applicable; Voice buffer limit; Show profile name; Keyboard layout; supported Volume/Haptics/Brightness | Voice retention setting is Core-owned even though placed here; do not invent unsupported hardware controls |
| Profiles / Identity | Current/default profile; switch/add/rename/remove; profile password change; My address/QR; Generate new address | Public host/SDK management, correct authorization and phase-aware results |
| Advanced | Unseen/pending quotas, concurrent-connection limits, recovery/idle timing, cache/reuse transport tuning, IPC limits, permitted external sink, rejection policy, raw history, safe platform diagnostics | Expose only documented safe descriptors; no transport concepts in ordinary messaging views |

A setting labelled `Receive Drops` must reflect the exact Core descriptor. If the accepted setting also restricts sending/commit, state that scope rather than misrepresenting it as receive-only. Do not add a GUI-only receive policy that bypasses Core.

### GUI-SET-03 — Final GUI preference defaults

These are newly consolidated GUI defaults, not claims about an existing implementation:

| Preference | Default | Scope / behavior |
| --- | --- | --- |
| Auto-play default | Off | Protected per-profile GUI preference; new logical LIVE contexts only |
| Per-context auto-play | Copy global default | Volatile per logical context; navigation/recovery preserves, runtime loss resets |
| Keep Live active while locked | Off | Per-profile GUI policy; never implicitly disconnects background LIVE |
| Accept Live while locked | None | Per-profile policy checked/frozen by Core |
| Lock screen notifications | Anonymize | Applies before any restricted presentation |
| Unlock method before explicit setup | Profile password | None never selected implicitly; PIN verifier remains Core-owned |
| Screen/application idle timeout | 120 seconds | User inactivity; an explicit disabled choice requires a clear safety warning |
| Show profile name on lock screen | Off | Landing view/privacy behavior in section 14 |
| Keyboard layout | QWERTY | QWERTZ selectable; OS physical-key mapping is not overridden |
| Software keyboard | Touch/device automatic; desktop explicit | No duplicate keyboard forced during ordinary desktop typing |
| Pins | None | Protected per-profile peer-linked ordering once created |
| External notification sink | Do not enable from GUI | Core effective default/policy remains authoritative |
| Clipboard export | Disabled | May be explicitly enabled only by an allowed platform policy |

Core defaults such as `daemon.auto_accept_contacts=false`, `daemon.send_read_receipts=false`, finite resource limits and existing fallback policy are read from the accepted registry. Do not silently change them as part of first GUI launch. Lowering a limit never deletes existing pending/unseen content.

### GUI-SET-04 — Safe changes and hardened visibility

When a setting changes, show the actual scope: profile override versus shared application/global setting where relevant. A GUI session cannot silently alter another profile. Core validates the change and publishes authoritative state. Pending updates/errors do not appear as successful toggle changes.

Hardened device UI does not expose Tor/SQL debug logging, plaintext runtime DB mirror, plaintext-profile enablement, arbitrary daemon-port wiring or irrelevant remote-profile internals. These may remain supported CLI development capabilities. Normal desktop GUI also does not gain dangerous debug toggles merely because its hardware is a PC.

An external file/webhook sink, if allowed under Advanced, needs a clear metadata-export warning and remains content-free. The GUI neither enables it automatically nor routes messaging/network traffic itself to that sink.

Security-policy changes while restricted require normal access and any full-password strength required by Core. They apply to the next granted lock cycle; the restricted client cannot silently increase its present privileges.

---

## 17. Profile switch, GUI close and normal shutdown

### GUI-LIFE-01 — Explicit profile switch

Settings Profiles invokes the public profile-runtime coordinator, not the peer-focus `SwitchCommand`. Selecting a different profile before initial activation is simply startup selection; switching an already running profile is a lifecycle transaction.

If relevant LIVE state exists, show a concise summary such as active connection count and pending count, with Cancel/Switch. Include other attached-client consequences where the public coordinator reports them: hard-locking that profile affects its other clients. Do not imply that an explicit global runtime switch only affects this window.

If no relevant state/drafts/shared-client consequence exists, do not insert an unnecessary warning. If disposable drafts will be discarded, state that consequence in the one required confirmation rather than hiding it or displaying a chain of modals.

### GUI-LIFE-02 — Transition phases and failure

Freeze new local capture/actions. Finalize authorized active LIVE capture and await its local accepted finalization/preservation result. Stop/finalize DROP capture as needed, then cancel this GUI's uncommitted DROP drafts under their ownership policy. Invoke normal Core exit/preservation, not purge.

Core applies current eligible fallback policy, preserves pending LIVE when fallback is Off, ends the old profile's LIVE activity and safely releases/hard-locks its runtime. It need not wait for remote DROP delivery. Only after that boundary clear old-profile presentation and attach/authenticate the target profile with its own credentials. Subscribe, snapshot and hydrate before installing the new active view.

Use phase-aware results. If failure leaves A active, render that truth safely. If A is already locked and B fails, stay in an explicit selection/unlock failure surface. Do not auto-unlock A to simulate rollback, reuse its proof for B or install a half-bootstrapped B. Retry/cancel cannot revive abandoned callbacks or send commands to the wrong profile.

Returning later to A restores its current pending/unseen state disconnected where reported. No implicit reconnect/fallback from returning. A real independently authorized Core recovery/delivery action is not attributed to GUI navigation.

### GUI-LIFE-03 — Desktop window close / GUI exit

Window close means close this GUI, **not** power off the computer, hard-lock the shared daemon or end other clients' LIVE activity by default.

Finalize this GUI's active authorized LIVE capture locally; cancel only its uncommitted DROP drafts; stop its playback/capture; clear volatile state; detach and exit. Existing committed DROP and pending LIVE remain Core-owned. If local finalization cannot be confirmed, use the protected owner-loss/recovery contract and show the truthful error/exit choice; never force-drop delivery-critical state.

Window close does not call `PrepareProfileExit` merely for convenience. The base runtime's ownership/autostart contract determines its independent service lifecycle, not a GUI assumption that it owns the process because it launched it.

### GUI-LIFE-04 — Physical Power actions

On a configured device, short Power-release performs normal screen off/restricted lock. Long Power opens the minimal menu `Power off` / `Cancel`; merely opening it does not shut down or purge. Default long-press threshold is 2 seconds and is a tested input constant, not a layout measurement.

Normal Power off confirms local-safe Core exit/preservation, then invokes the registered authorized local shutdown adapter. It does not wait for remote message delivery. If preparation is unconfirmed/failed, keep the device on in an actionable safe state; no success fiction.

A remotely attached profile does not grant permission to power off the remote host or to destroy local files as though they belonged to it. Appliance shutdown requires a validated local host/runtime binding. Full-appliance configuration must define single-active managed-runtime ownership; if other local runtimes could be interrupted without safe preparation, refuse automatic host shutdown until the host coordinator resolves them. Desktop close remains independent.

---

## 18. Emergency purge and physical-input priority

### GUI-PURGE-01 — Authorized trigger only

Purge is not an everyday GUI menu action. On an explicitly configured physical appliance, hold Power + PTT together for **5 continuous seconds** to arm/trigger the emergency operation. Use unmistakable permitted physical feedback and an optional minimal visible state. No accidental global desktop keyboard shortcut is bound to real purge.

Core must have granted the current client the required prior-authenticated, immutable profile/runtime-scoped lifecycle capability. A hardware event is not authentication. Cold boot, a new unauthenticated GUI, a hard-locked runtime with no live grant, or a remote/untrusted binding cannot use the chord to bypass access controls. Show only a safe unavailable indication; do not promise the chord works in every boot state.

No new GUI setting restores a globally anonymous purge path. In particular, do not resurrect an obsolete Boolean setting as a substitute for the accepted D01 capability.

Any additional conservative authorization check in the actually accepted Core must still be obeyed. A denied operation stays denied. Record a discrepancy against the adopted D01 contract in the integration map; never resolve it by toggling an unrelated setting or granting the GUI a bypass.

### GUI-PURGE-02 — Chord arbitration

Once the two-button chord is detected, it takes priority over ordinary PTT and the long-Power menu. Do not begin a new Voice item from its PTT edge. Suspend further ordinary local capture submission and normal Power actions while arming; already admitted data is not retroactively unsent.

If arming is cancelled before threshold, consume the chord until both controls are released. Finalize any previously authorized interrupted recording under normal policy as necessary; do not dispatch a delayed Power-off/Lock event or automatically start a new recording. A cancelled chord cannot silently discard previously accepted LIVE data.

At the threshold, submit exactly one authorized SelfDestruct operation bound to the initiating profile. After acceptance, do not finalize for delivery, fallback, reconnect, flush messages or resume normal notifications. Stop GUI producers immediately. Destruction and race fencing remain Core-owned.

### GUI-PURGE-03 — Truthful milestones and power control

Distinguish: arming, accepted/fenced, persistent key-protection removal, runtime-key release, combined documented irreversible/power-off-safe milestone, file cleanup, completed, partial failure and unknown result. Use actual accepted event names and operation identities from the integration map.

`SelfDestructInitiated`, IPC EOF, timeout or process exit alone is never proof of successful destruction. Keyslot removal alone is not automatically proof that all relevant runtime access has been released. Only the Core's documented combined safe guarantee can authorize this operation's device shutdown.

After confirmed safe destruction and terminal cleanup success/failure, invoke local device shutdown immediately. A cleanup failure after the safe milestone is reported as incomplete cleanup, not complete success; it must not restore keys. If the safe milestone is received but terminal cleanup reporting is lost, a bounded best-effort completion wait may end in shutdown **only** when that already received milestone explicitly guarantees power-off safety. Document the chosen local wait in the platform implementation; do not wait for network delivery.

If safety/destruction is unknown or key release failed, show a critical safe error and do not cut power automatically based on guesswork. A reconnect/status query may use only the documented authorized destruction-status mechanism; it cannot unlock/recreate the profile to inspect it.

Purge affects only the selected profile. Device configuration and unrelated profiles are not swept. Clear this GUI's profile buffers promptly and invalidate all old callbacks. Simulator never performs production destruction or host power-off.

---

## 19. Clipboard, rendering, permissions and safe wording

### GUI-SAFE-01 — Clipboard policy

Clipboard export defaults Disabled. Text Copy and address Copy appear only under an explicitly permitted platform policy. A standard desktop clipboard may be allowed through a warned user choice; hardened devices may forbid it entirely or supply an isolated local clipboard adapter.

Do not put passwords/PINs/proofs into Copy actions. Paste never executes QR commands, markup, URLs or shell text. A best-effort clear on exit/lock may run only if the adapter can verify it still owns the current clipboard value; do not erase unrelated user data. Do not promise removal from clipboard history, synchronization, screenshots or other applications.

The profile's sensitive data never enters OS notification previews by default. Camera/microphone/system permissions are requested at the time of explicit use with truthful explanations. No background camera scanning or microphone recording starts at boot, navigation, reattach or unlock.

### GUI-SAFE-02 — Plain rendering and assets

Peer text, aliases and errors are rendered as bounded plain content, not interpreted HTML/Markdown, scripts or executable links. No rich link previews or automatic URL requests. Use the accepted validation rules and safe presentation limits without modifying the message's canonical identity or fabricating content.

Package fonts/icons and other allowed assets locally with appropriate redistributable licensing in the implementation. Do not depend on a CDN, Figma subscription, online icon service or cloud font fetch at runtime. Layout delivery must include usable assets/tokens or explicitly identified redistributable sources, not only inaccessible design-tool links.

The GUI's direct network behavior is limited to its configured public SDK endpoint and explicitly authorized platform services. Messaging, Tor, detached notification sinks and reliability remain Core-owned. No GUI telemetry, analytics, update checks or package downloads are added.

### GUI-SAFE-03 — Wording and status truth

Use plain action/state language:

```text
Could not start Live
Connection lost
Could not change route
Message could not be queued
Recording could not be finalized
Voice buffer full
3 Live messages queued as Drops
Queued messages are not cancelled
```

Distinguish locally accepted, pending, remotely delivered and actually received read state. `No connection` is not `Peer offline`. `Connected` means an actual current LIVE fact, not a guessed presence indicator. Generic auth failure must not reveal profile/password/PIN data.

Status, disabled action, progress and destructive consequences cannot be communicated by color alone. English casing may be refined in layout; the semantic distinction must remain testable.

---

## 20. Platform implementation, technical choices and resource bounds

### GUI-PLAT-01 — Adapter boundaries

Keep view models independent of toolkit widgets and physical libraries. Required interface areas are display/window, touch/pointer, PTT/Power input, application/OS focus, capture, playback/routing/AEC, camera/QR input, indicator, haptics, clipboard and authorized local shutdown.

Provide functioning desktop adapters and explicitly marked simulator adapters. Physical adapters are registered, schema-validated and tested against declared devices. Optional components may be unavailable; the full dedicated-device deployment requires its declared essential input/display/power and communication hardware.

Audio workers never manipulate widgets directly. View models do not call GPIO, start Tor, open SQL, access key material or invoke arbitrary shutdown commands. The GUI process is not required to have root privileges; privileged device operations use appropriately limited host/platform interfaces.

### GUI-PLAT-02 — Bounded technical-selection work package

This specification intentionally does **not** fix the rendering toolkit, exact panel pixel size or hardware board before the layout/device design round. These are explicit delegated decisions, not permission to change the product model.

Before implementing all screens, the coding agent must create `GUI_PLATFORM_ADR.md` and demonstrate a narrow vertical slice against the approved layout and accepted SDK. The ADR must select and justify:

- one non-webview production rendering stack and its actual installable/native dependencies;
- supported Python/OS/architecture combinations inherited from the accepted repository, with Windows desktop and Linux desktop as required product targets;
- concrete physical-device support, separately from Linux desktop; Raspberry-Pi-class operation is a design target, not proof that an unselected Pi Zero/ARM variant can run the chosen toolkit;
- rendering backend, scaling/rotation strategy and input translation for the approved layout's reference/minimum sizes;
- one interoperable baseline Voice codec/container contract, incremental framing, duration/time mapping, safe seek/checkpoint rules and decoder limits, reusing the accepted protocol where already defined;
- native capture/playback/routing and actual AEC strategy, including headset/speaker validation;
- registered adapter IDs, exact driver/binding schemas and supported sample device files;
- protected GUI preference/staging APIs and any precisely scoped integration dependencies;
- dependency licensing, offline install/build behavior and actual test evidence.

Toolkit/native dependency choice belongs in this technical work package, not hidden inside the visual layout. It cannot replace the public SDK, require a hosted web app or split desktop/device into different product UIs. If a proposed stack cannot meet declared platform/layout constraints, resolve that technical choice before building every screen.

A camera, LED or haptic mock is not evidence of hardware support. A desktop window on an ARM machine is not automatically a verified physical touchscreen/Power/PTT appliance. Ship a support manifest that distinguishes supported, development-only and untested configurations.

### GUI-PLAT-03 — Audio capability and full-duplex validation

The declared supported audio configuration must allow simultaneous local capture and remote playback. Speaker operation needs a real tested AEC/routing solution. Ducking/gain control may complement it but must not impose a half-duplex protocol or be falsely labelled successful echo cancellation.

Where the platform cannot meet speaker/AEC requirements, show a truthful unsupported-route/headset-required capability rather than silently treating mock/ducked output as full hardware acceptance. Text may remain usable; full Voice/appliance acceptance requires a proven supported audio route.

Test real codec decode, incremental arrival, resumed data, concurrent capture/output, permissions, unplug/replug and failed devices on the declared platform. Recording timers derive from accepted capture/media timing, not UI repaint count. Do not fabricate duration from peer-declared byte size.

### GUI-PLAT-04 — GUI-owned baseline budgets

The GUI must bound queues and caches independently from Core's authoritative pending/unseen limits. These are implementation baselines for V1; a deployment may use lower validated budgets. Raising them requires an explicit measured support/profile change, not a GUI setting that makes them unbounded.

| Resource | Baseline maximum | Overflow behavior |
| --- | --- | --- |
| Notification Center | 128 entries and 128 KiB serialized sanitized metadata | Coalesce/evict info entries; preserve actionable Core references via resnapshot, never mutate messages |
| Pending GUI-dispatch queue | 512 queued records and 4 MiB payload memory | Coalesce replaceable state; recover media from Core where supported; explicit overload for nonrecoverable events |
| Reusable GUI encoded-media cache | 16 MiB, profile-scoped | Evict only unleased volatile copies, remove corresponding replay/resend capability; never delete Core pending/unseen data |
| Decoded output/jitter working buffers | 4 MiB total | Flow control and bounded buffering; no false completion or silently mixed peers |
| Unaccepted local capture/encode submission buffer | 1 MiB | Stop admission/capture and finalize already accepted complete prefix; report refused tail, no silent success |
| Volatile text drafts | 32 contexts and 256 KiB total, each bounded by Core message-size rules | Reject further draft growth/creation with clear notice; no silent overwrite of another draft |
| This GUI owner's DROP Voice review drafts | 8 contexts, also constrained by Core staging bytes/count | Refuse another draft until one is sent/deleted; preserve all admitted drafts |
| Current-runtime LIVE presentation items | 1,000 cached items and 2 MiB text/descriptor metadata | Evict only presentation copies safely; Core inventory remains authoritative; no hidden transcript persistence |
| Persistent GUI peer-linked preferences | 128 pins and 64 KiB total metadata per profile | Refuse additional metadata, no content/alias side store |
| Device file | 64 KiB | Reject before parsing/activation |

These caps are logical payload/accounting limits, not a claim that toolkit/Python process RSS equals their sum. The ADR must measure total process memory, allocations, decode working sets and target-device behavior. A single retained Voice item larger than the optional replay cache must still be streamable with bounded public reads; cache capacity is not an invented message-size limit.

Never buffer an entire large recording solely to draw a row or seek to a time. SDK/codec may use bounded indexed reads. If a safe operation needs more temporary memory than supported, surface inability and preserve Core data rather than silently consuming/deleting it.

### GUI-PLAT-05 — Responsiveness and diagnostics

Use state machines/reducers, not random widget mutation from network callbacks. Long I/O/decoding runs outside the UI loop with cancellation tokens. PTT release, lock and purge admission are high-priority input paths and must not sit behind a long history/render batch.

Acceptance uses deterministic synchronization and virtual clocks for logic, and measured native responsiveness under the declared load for the platform slice. Record actual target hardware, queue occupancy, memory and input latency; do not invent a universal frame-rate claim for untested hardware.

Diagnostics expose safe capability/state summaries and selected configuration source, not secrets, full peer payloads or uncontrolled exception dumps. A startup label `Desktop / built-in defaults` is diagnostic information, not a mandatory user-facing warning.

### GUI-PLAT-06 — Semantic indicators and haptics

The platform indicator interface supports semantic states `off`, `locked_live_active`, `transmitting`, `receiving`, `purge_arming` and `critical_error`. These are semantic requests, not a set of hardcoded GPIO writes in a view model. The platform/layout packet supplies actual permitted patterns and accessibility-equivalent cues.

Destructive arming/critical failure takes priority over ordinary activity, followed by current authorized transmission/reception and then the continued-LIVE idle indication. Keep the state vocabulary small. When both media directions are active, the chosen pattern must not imply that the system is half duplex.

With locked notifications Off, unrelated unsolicited traffic never triggers LED/haptic/wake behavior. The exact explicitly continued LIVE context may still have a non-identifying media-safety indication. Local capture must remain unmistakable even without an LED through the permitted GUI/hardware capability; absence of optional haptics is not silently replaced with host notifications.

---

## 21. Contract for the next layout/design round

### GUI-DESIGN-01 — Design input and freedom

The designer receives **this document**. The output is the approved companion `METOR_GUI_LAYOUT_SPEC.md` plus local visual assets/reference renders. No GUI implementation agent should need to infer missing security state from a single happy-path image.

The layout round may choose exact screen compositions, responsive/master-detail arrangements, typography, spacing, colors, icon style, visual controls, final non-security-sensitive copy and animation within this product model. It may not merge DROP/LIVE, add a Home/bottom-navigation product layer, automatically call on a tab switch, expose hidden histories, weaken authorization or remove required actions.

Touch-first does not authorize unusable desktop keyboard focus. Desktop support does not authorize removing the on-device keyboard/PTT/lock flows. Use one coherent component language across both.

### GUI-DESIGN-02 — Required companion deliverables

The companion MUST contain:

| Deliverable | Required content |
| --- | --- |
| Identity/version | This functional-spec version; layout version; approved references/assets; a change log |
| Display contract | Reference device logical/physical sizes, smallest supported size, orientations, desktop default/minimum/resizing rules, scale/density mapping and safe areas |
| Screen coverage | Every V01–V23 role mapped to an approved screen/state/panel or explicit reusable composition, without silently omitting states |
| Action coverage | Every applicable A01–A25 action mapped to visible/contextual controls with labels, eligibility, confirmations and disabled/error treatment |
| State variants | Loading, empty, long/many items, active/recovering/ended, auth/cooldown, Voice recording/finalizing/review, buffer-full, stale request, capability failure and privacy modes |
| Component contract | Header/selector/list row/bubble/Voice control/composer/keyboard/call overlay/notification/settings/auth/confirmation/error/indicator components with states |
| Design tokens | Named color, text, spacing, size, radius, stroke, icon and motion tokens; accessibility rules and state contrast; no undocumented literal style choices scattered through implementation |
| Interaction specification | Focus/Tab order, touch targets, pointer/press/release/long-press, keyboard use, Back, overlays, scroll anchoring, PTT release-required and race-safe busy states |
| Media presentation | Recording timer, immutable placeholder chronology, review controls, manual playback/live-edge jump, unknown/incomplete duration and unavailable resend |
| Privacy rendering | Off/Anonymize/Show all, hidden profile name, clipboard-disabled state, no preview in any notification/window title/accessibility path |
| Assets | Local exportable icon/vector/raster assets, font names/licensing references, permitted fallbacks and exact token/asset mapping; no runtime external fetch |
| Acceptance references | Reference renders or golden fixtures for normal, minimum-size and selected edge states; view/action IDs and this document's requirement IDs |

Do not invent actual screen dimensions in this functional document and then call them a finished layout. The approved companion must provide those values before implementation can hardcode or validate presentation sizes. The device parser still validates actual hardware dimensions and rejects unsupported layouts safely.

### GUI-DESIGN-03 — Mandatory visual edge-case set

At minimum, show all of the following in the design packet:

- root DROP empty, pinned, pending-only and long-label state;
- root LIVE with multiple active/recovering/disconnected/unseen contexts;
- idle LIVE without a call, active LIVE, recovery and terminally ended pending state;
- outgoing PTT while incoming text/Voice continues, with stable placeholder and composer exclusivity;
- DROP recording and unsent Play/Delete/Send review;
- manual playback behind live edge, explicit LIVE jump, unavailable/partial media and cache-evicted resend;
- new-item scroll affordance without forced scroll;
- incoming requests while another peer is foreground, with Accept distinct from Open;
- multiple anonymous pending calls, expiry and denied Accept retaining Decline/unlock;
- locked Show all/Anonymize/Off, plus explicitly continued LIVE under Off;
- PIN, password, None, forgot-PIN, cooldown and hidden-profile-name states;
- profile switch with relevant pending state and failure after old profile is locked;
- desktop close versus appliance Power off, and distinct purge arming/safe/unknown/failure states;
- no microphone/camera/output, invalid device file and no-display operational outcomes;
- keyboard-visible smallest supported view, high scale, long English copy and complete keyboard focus path.

A failed/unavailable state may be specified textually if no graphical output exists, but its user/service behavior must be defined.

### GUI-DESIGN-04 — Implementation-facing design packet

Provide a one-to-one mapping such as `V09 / recovering -> component tree -> tokens -> reference render -> action eligibility -> GAT test IDs`. Screenshots alone are insufficient. HTML can be a static design reference, not permission to replace the production GUI with a webview.

The designer is not responsible for implementing GPIO, cryptography, codec framing or the IPC reader. Device geometry/controls constrain design; adapter realization and codec/toolkit proof belong to the technical ADR. Any design that requires a new physical control or changes a functional rule must call that out for an explicit spec revision before it becomes implementation input.

---

## 22. Agent implementation work packages

### WP-G0 — Establish the accepted contract and design baseline

Read this specification and the approved companion in full. Record the accepted Refactor-2 SHA, namespaces, public SDK/IPC/launcher versions, capability names, supported platforms and source of generated docs. Run the existing repository gates before changing code.

Create `GUI_INTEGRATION_MAP.md`: requirement -> actual public operation/interface -> owner -> version/capability -> failure behavior -> test. Identify narrowly scoped dependencies such as disposable owner-qualified staging, protected GUI preferences, deferred graphical bootstrap and retained-item read semantics. Do not treat the old review commit as proof that these interfaces exist.

No production screen build starts from an unapproved visual guess. A static prototype from the design round is not a substitute for the accepted layout contract.

### WP-G1 — Prove the platform/launcher vertical slice

Write the bounded technical ADR from section 20. Build and install the actual GUI wheel outside the checkout. Prove lazy `gui` registration, desktop startup with no device file, graphical authentication/autostart interaction, a minimal layout-approved view, native input/capture/playback path, safe simulator containment and device-config validation.

Validate platform/install feasibility early. Do not implement every screen atop an unproven renderer, claim placeholder drivers work or quietly require the Terminal UI as a bootstrap dependency.

### WP-G2 — State/data/security foundation

Implement typed view models, generation-tagged event routing, attach/snapshot/inventory reconciliation, bounded queues/caches, protected GUI preferences, disposable staging integration, auth/restrict/reauth state and capability-driven action eligibility. Add deterministic tests before adding large view trees.

Public host/Core additions required by this foundation belong in their proper packages and must preserve Terminal tests. No direct profile storage access from GUI.

### WP-G3 — Navigation, contacts and text

Implement root/peer DROP/LIVE, entry intent, Back, contextual Start/Accept/Open/Decline, contacts/QR/My identity, projected history and text behavior against actual SDK operations. Bind all visible controls to stable action IDs and the approved component/token contract.

Verify that navigation sends no communication-changing command and that no unknown state is optimistically presented as established.

### WP-G4 — Media and reliability presentation

Implement normalized PTT, exact target binding/re-arm, DROP review, safe owner loss, full-duplex input/output, incremental playback, coverage/release, auto-play eligibility, timeshift, scroll anchoring, quotas, fallback and delivered resend availability. Test storage/capability/unknown-result failure paths as well as happy paths.

Do not implement Tor/replay/fallback inside GUI to work around a Core contract defect.

### WP-G5 — Lock, notifications and lifecycle

Complete privacy-projected overlays/Notification Center, PIN/password/None and escalation, locked LIVE scope, profile transition phases, desktop close, appliance Power off and authorized purge. Test multiple clients and a GUI with no previous volatile state.

Simulated physical actions never affect real profiles/host power. Report real hardware testing separately.

### WP-G6 — Layout fidelity, packaging, docs and release readiness

Apply the companion's approved tokens/assets, all state variants, sizing and accessibility behavior. Add visual fixtures as a secondary layer over functional tests. A change to product behavior requires a spec revision, not merely a screenshot update.

Extend the existing canonical build/release/installer machinery to the real GUI wheel and its native dependencies. No competing publication workflow. Preserve base-only/SDK-only/Terminal-only installs and co-install/uninstall safety. Run lint/type/format/tests over all new source roots.

Update lasting runtime/operator documentation, the GUI contract and generated docs through their generators. Produce a traceable acceptance report with exact commands, environments, versions, results, skips, hardware measurements and remaining limitations. Do not publish a release or overwrite tags as part of normal implementation without a separate owner instruction.

---

## 23. Acceptance scenarios and required evidence

Each GAT row is a **test group**, not necessarily one unit test. Implement deterministic state-machine tests and public-contract integration tests, supplemented by native desktop/device and layout checks as applicable. Preserve the original 30 scenario meanings with the explicit corrections below. Tests must exercise production enclosing paths, not only conveniently mocked helpers.

### 23.1 Product scenarios retained and corrected from the original GUI document

| ID | Scenario | Required proof |
| --- | --- | --- |
| GAT-01 | Root navigation | Unlock -> root DROP -> LIVE -> Contacts/Settings/Notifications -> Back. No call/accept/reject/end/fallback/route command arises from navigation. Peer LIVE tab with no connection stays idle until Start Live. |
| GAT-02 | Start DROP via QR | DROP New -> scan/validate -> alias -> Save & Open Drop opens correct peer once. No root conversation until real published DROP state. Cancelling/invalid/self QR has no send/call side effect. |
| GAT-03 | Start LIVE via QR | LIVE New -> Save & Start Live saves and initiates one explicit request. Existing active/recovering peer opens without another ring. Save failure cannot proceed to call. |
| GAT-04 | Multiple LIVE contexts | Alice foreground, Bob active background. Only the eligible foreground may auto-play. Switching peers revokes old output, preserves same-runtime per-context override and never transfers PTT implicitly. |
| GAT-05 | Incoming while elsewhere | Alice DROP foreground, Bob calls. Accept keeps Alice visible and Bob background/silent. Open revalidates and opens Bob LIVE. Expired Open does not call Bob back. |
| GAT-06 | PTT context switch | Hold Alice PTT -> Open Bob. Alice local turn finalizes/preserves; Bob cannot record before release and a fresh press. No retarget, duplicate ID or context-disconnect side effect. |
| GAT-07 | Full duplex | Local PTT plus incoming text and Voice/eligible output continue. The same GUI's keyboard/text composer is deliberately unavailable during recording and returns afterward. Core/other clients remain full duplex. |
| GAT-08 | Manual timeshift | Auto-play Off; receive an arriving Voice; Play starts from retained beginning. LIVE jump uses a valid decoder checkpoint, bounded buffers and no duplicate playback or false consumption of skipped content. |
| GAT-09 | Scroll anchoring | Scroll upward/play older item while new items arrive. No forced scroll; new-item affordance restores view edge without starting audio/call or consuming hidden Voice. |
| GAT-10 | DROP Voice review | PTT-down/release creates an unsent review with Play/Delete/Send. Play does not commit. Send commits exact draft once; Delete cancels exact unsent draft. Keyboard behavior is correct. |
| GAT-11 | Voice recovery | Network loss during held LIVE capture preserves ID, target and accepted prefix; genuine recovery uses Core resume. No automatic microphone restart on GUI reattach. |
| GAT-12 | Buffer pressure | Warn at declared pressure; test exact hard limit and a chunk that would cross it. Finalize accepted codec-valid prefix once, require release, reject new capture until correct capacity returns. DROP remains review. |
| GAT-13 | Fallback Off | Ended context with three pending own items remains actionable without forced modal/TTL. Select one fallback; only that same ID becomes DROP. Others stay pending LIVE. |
| GAT-14 | Delivered resend | Own delivered LIVE text and complete available Voice can be resent as new DROP IDs. Received LIVE has no forwarding action. Missing/evicted source cannot be resurrected to satisfy resend. |
| GAT-15 | Auto-fallback feedback | Core converts eligible pending LIVE after failed recovery. GUI says queued/converted, not remotely delivered. No content preview; resulting projections match actual IDs. |
| GAT-16 | Backlog overflow | Local Core safety termination shows typed system reason; remote view shows only its allowed generic reason. No peer-local quota disclosure, fake local-user actor or forced pending deletion. |
| GAT-17 | Contact rename | Rename pinned Alice -> Anna. Same identity/pin/order and conversation survive; all labels and accessible names update consistently. |
| GAT-18 | Contact demotion | Remove saved peer with retained/active state. Saved row disappears; Core anonymous alias replaces old labels in all views/caches/notifications. Communication remains according to Core. |
| GAT-19 | Save discovered peer | Relevant anonymous DROP/LIVE context -> Save contact. Core promotion updates labels and Saved Contacts without new message identity or implicit connection. |
| GAT-20 | Lock with continued LIVE | Explicitly enable, foreground Alice, lock. Exact granted context may use PTT and optional auto-play; Bob never inherits. Test auto-play Off and notification Off independently. |
| GAT-21 | Lock outside LIVE | Lock from Settings/root/DROP with Bob active in background. No continued target, no PTT or auto-play, no implicit disconnect of Bob or other clients. |
| GAT-22 | Locked incoming privacy | Show all/Anonymize/Off with multiple calls and All/Saved/None acceptance policy. No forbidden identity or Off activity; denied anonymous Accept preserves permitted Decline/unlock. |
| GAT-23 | Unlock methods | PIN/password/None, forgotten PIN, three failures, cooldown, password recovery and next-cycle PIN. Cold/new-client/hard lock never accepts PIN as root authentication; credential change requires proper full strength. |
| GAT-24 | Profile switch | Active/pending LIVE triggers accurate warning. Finalize locally, discard own uncommitted drafts, safely exit A, clear presentation, authenticate B, then hydrate. No old-profile callbacks/data. |
| GAT-25 | Return to pending profile | A has pending LIVE with fallback Off -> B -> A. Pending is restored disconnected; no implicit reconnect/fallback, no restoration of prior GUI draft/Notification Center. |
| GAT-26 | Normal power-off | Configured appliance, active recording -> explicit Power off. Safe local finalization/preservation precedes platform shutdown. No remote-delivery wait or shutdown on failed preparation. |
| GAT-27 | Purge precedence | Authorized physical chord with capture/recovery/pending work. Exactly one scoped destruction, no post-acceptance finalization-for-delivery/fallback/reconnect, no host power-off before actual safe milestone. |
| GAT-28 | GUI crash/restart | Lose text drafts, own disposable uncommitted DROP Voice drafts, Notification Center and consumed LIVE cache. Retain committed/pending/unseen Core work and other clients' drafts. Reauthenticate and discover retained IDs; never auto-send. |
| GAT-29 | Privacy settings | Ephemeral DROP and disabled activity histories produce no GUI substitute history, persistent notifications/previews or reconstructed consumed LIVE payload after restart. Protected UI metadata remains minimal/scoped. |
| GAT-30 | Read receipts | Default local emission Off; local handoff still works. Valid incoming READ can be shown regardless of local emission preference; absent READ is unknown. Voice placeholder/download is not consumption. |

### 23.2 Post-refactor, platform, integration and layout scenarios

| ID | Scenario | Required proof |
| --- | --- | --- |
| GAT-31 | Installed GUI wheel | Build/install outside checkout with no PYTHONPATH/editable dependency. Real public imports, registration and GUI launch work without Terminal installed. |
| GAT-32 | Wheel ownership | SDK/base/Terminal/GUI RECORDs have non-overlapping files. Co-install and remove each UI without deleting another package's code. SDK-only/base-only use remains valid. |
| GAT-33 | Lazy help | Every help path works with GUI absent, installed, broken or unconfigured; no toolkit/device/auth/daemon side effect and no internal Terminal chat guide in CLI help. |
| GAT-34 | UI selection | Explicit --ui > environment > common default > Terminal. Device-file existence and installed GUI do not change selection. Missing/duplicate/incompatible provider errors are distinct and never silently switch frontend. |
| GAT-35 | No-file desktop | Explicit/default-selected GUI with no requested device file opens real desktop mode and authenticates graphically. No missing-TOML warning, file creation or automatic simulator activation. |
| GAT-36 | Explicit file errors | Missing/unreadable/malformed/oversized/unknown-version config fails before daemon/driver/capture side effects. No desktop/mock fallback. |
| GAT-37 | Config resolution | CLI path overrides METOR_DEVICE_CONFIG; no implicit working-directory/system/profile discovery. Relative path resolves once. Device options on actual Terminal launch reject clearly. |
| GAT-38 | Device schema safety | Strict types, numeric limits, known IDs and driver parameters, distinct PTT/Power bindings. Unknown import/shell/path payload cannot run code or activate unsafe drivers. |
| GAT-39 | Display and optional hardware | No desktop display reports display failure, not universal TOML requirement. No mic/camera/output disables only dependent actions; unavailable playback never consumes Voice. |
| GAT-40 | Simulator isolation | Configured simulated hardware creates no real driver, purge or host-power side effect. Ordinary desktop is visibly/behaviorally distinct. Real-Core tests use only explicitly isolated temporary profiles. |
| GAT-41 | Graphical bootstrap | No terminal prompt in no-TTY GUI entry. Autostart never/ask/always and explicit overrides work graphically; remote endpoint never autostarts a local substitute. |
| GAT-42 | Failed bootstrap/snapshot | Auth failure, cancellation, mismatch, retryable snapshot-unavailable and endpoint loss produce safe retry/selection; no partial stale communication view enabled as authoritative. |
| GAT-43 | Empty-state media discovery | Fresh GUI with no known message IDs inventories pending/unseen media and permitted metadata through public API. No private SQL/blob access or consume-on-inventory. |
| GAT-44 | State versus media ordering | State snapshot revision cannot discard content/request/lifecycle events. Epoch/context replacement revokes old grants; media offsets and dedupe avoid missing or doubled playback. |
| GAT-45 | Slow callbacks/overload | Slow render/decoder, full GUI queues, callback-request and disconnection do not deadlock IPC or grow unbounded. Recoverable catch-up and unrecoverable overload are explicit. |
| GAT-46 | Duplicate actions/unknown results | Double click, key repeat, delayed response and send/commit timeout keep one operation/message ID. Reconcile unknown result; never blindly queue a second send. |
| GAT-47 | Input-source arbitration | Physical/pointer/key down-repeat/up/cancel/lost-focus/unplug cannot steal a turn, create stuck capture, bypass Release-required or synthesize a press on resume. |
| GAT-48 | Review draft collision | A second PTT press for a peer with review does not overwrite it. Navigation returns to same owner/peer review; another peer's review is independent and bounded. |
| GAT-49 | Disposable staging ownership | Owner loss, hard lock, close and profile switch clean only this GUI's uncommitted DROP staging. Another client's recoverable drafts and committed/unknown-commit winners survive correctly. |
| GAT-50 | Interrupted LIVE producer | Crash before LIVE finalization retains accepted bytes under typed producer-loss recovery; no permanent wait on a vanished producer and no unsent-DROP cleanup sweep. |
| GAT-51 | Media failure boundaries | Capture/codec/append/finalize/commit errors preserve known admitted content and correct draft/pending state. No fake playable/sent result or need for a restart to expose a known rejection. |
| GAT-52 | Incremental decoding/seek | Declared codec/container, checkpoints, growing media, missing range and resume tested with real codec. No whole-recording re-read/decode for every small seek/read. |
| GAT-53 | Playback coverage/release | Partial play, live-edge jump and download do not falsely consume full Voice; finalized complete playback/handoff releases exactly the permitted identity and obeys read-receipt policy. |
| GAT-54 | Auto-play transitions | Global Off default, per-context override, mid-turn foreground acquisition, context departure, manual priority and return-to-peer produce no old-backlog surprise playback. |
| GAT-55 | Large items/cache limits | Stream an item larger than reusable cache; measure bounded working set. Evict only eligible volatile copies, remove resend/replay availability and never delete Core pending/unseen data. |
| GAT-56 | Restriction race/failure | Content is covered immediately; normal access denied while awaiting Core. Failed restriction never becomes fake success or spawns a hidden unrestricted replacement connection. |
| GAT-57 | Continued-context revocation | Genuine authorized recovery differs from terminal end. Later call from same Onion and accepted Bob cannot inherit Alice's old locked capability; capture stops/re-arms on revocation. |
| GAT-58 | Notification clear/staleness | Clear/Dismiss changes center only. Same unchanged fact does not instantly respawn; new generation can notify. Root counts remain correct; deleted/expired action targets are safe. |
| GAT-59 | Off historical count | When events were withheld, unlock resnapshots current state without invented since-lock total or hidden unrestricted event ledger. Allowed volatile counts are truthful and bounded. |
| GAT-60 | Anonymous handle races | Expiry, replacement, another client's action, denied Accept, unlock and reauthorization cannot reuse a handle for another call or disclose caller classification. |
| GAT-61 | Protected GUI preferences | Pins/peer-linked settings are protected, bounded and stable across profile rename; remove/purge removes correct metadata. No plaintext global contact/pin sidecar or device TOML leakage. |
| GAT-62 | Profile-switch failure | A-active failure, A-locked/B-auth failure, cancelled B bootstrap and stale completion render actual phase. No silent rollback/unlock or cross-profile credentials/callbacks. |
| GAT-63 | Desktop close coexistence | GUI window close with another authenticated client does not hard-lock daemon, end its calls or power off host. Own capture/draft cleanup follows the exact policy. |
| GAT-64 | Device Power arbitration | Short press, long menu, cancelled chord and held-key repeats yield one intended action. A remote/unowned runtime or unsafe other active local runtime cannot cause blind host shutdown. |
| GAT-65 | Purge result truth | Test initiated-only, EOF, timeout, keyslot-only, safe milestone, cleanup failure and unknown outcome. No false successful destruction, restored keys or premature platform shutdown. |
| GAT-66 | Purge authorization | Unauthenticated/new/cold/hard-locked/old-epoch/wrong-profile/remote-invalid caller cannot gain destructive rights from a physical event. No obsolete Boolean bypass reintroduced. |
| GAT-67 | Settings scope/defaults | New GUI defaults exactly match section 16; Core defaults remain from registry. Descriptor validation/scopes, first-run conservative lock and next-cycle policy updates are correct. |
| GAT-68 | Clipboard/rendering safety | Disabled copy, warned supported clipboard, ownership-aware clear, malicious text/QR/alias and accessibility content tests. No rich previews, executable markup, network asset fetch or secret logging. |
| GAT-69 | Minimum display/layout | Every required view/state remains operable at approved minimum/reference sizes, scale and orientation; keyboard/overlays do not cover essential actions. Unsupported geometry errors rather than clipping. |
| GAT-70 | Accessibility/design tokens | Keyboard focus/order, touch/long-press alternatives, labels, non-color cues and approved tokens/assets match companion. Golden fixtures include failure/privacy/busy states, not just happy paths. |
| GAT-71 | Real audio platform | On declared supported desktop/device route, simultaneous native capture/playback and actual AEC/headset behavior work. Mock results are separately labelled, not substituted. |
| GAT-72 | Native/device support manifest | Installed dependencies, concrete driver IDs, geometry and permissions are proven on claimed OS/architecture/device. Untested board variants are not advertised as working. |
| GAT-73 | Release/installer regression | Existing canonical build/installer workflow includes real GUI and correct dependencies; SDK/base/Terminal-only flavors remain. Linux/Windows wheel/installer smoke tests run outside checkout. |
| GAT-74 | Durable documentation | GUI runtime contract, device schema/sample configs, platform ADR, public integration map, generated schemas/settings and user/operator instructions match actual implementation. |
| GAT-75 | Complete handoff traceability | Every mandatory GUI requirement and V/A state maps to tests/layout/implementation or an explicit unresolved gate. No completion claim with a missing layout, unaccepted Refactor 2, skipped critical test or mock-only hardware proof. |

### 23.3 Evidence categories

Report separately: deterministic logic tests; actual public SDK/Core integration; installed-wheel/installer tests; native desktop interaction; real audio/codec/routing; physical-device tests; visual/accessibility fixtures. A mock pass does not imply native or hardware success.

Use isolated temporary profiles for all destructive/security tests. Inject failures at enclosing production boundaries, including asynchronous callback timing, owner loss, finalization/commit uncertainty, revoked permissions and device shutdown acknowledgment. Never test purge against the user's real profile merely to obtain a green report.

---

## 24. Definition of done and required deliverables

### GUI-DONE-01 — Product and design completeness

The GUI is complete only when it implements this functional specification and the approved companion layout against the accepted post-refactor contract. A static prototype, Terminal-wrapper window, toolkit demo or placeholder GUI wheel is not completion.

Required delivered artifacts:

- real `metor-ui-gui` source/package, local assets and exact dependency/build definitions;
- complete typed state/view/action implementation and required platform/simulator ports;
- `GUI_INTEGRATION_MAP.md`, documenting actual public API versions/imports/capabilities and any narrow additions;
- `GUI_PLATFORM_ADR.md`, concrete support manifest, device schema and tested sample configurations;
- approved `METOR_GUI_LAYOUT_SPEC.md` and token/asset/state mapping as implementation inputs;
- automated acceptance/regression tests plus native/visual/hardware evidence at the claimed support level;
- lasting `docs/contracts/GUI.md` and operator/install/development documentation;
- a historical/deprecation pointer from the old Embedded GUI assignment/contract so there is one authoritative GUI contract, while preserving any still-current frontend-neutral Core contract content;
- generated public API/settings docs regenerated through canonical tooling, not handwritten false schemas;
- final traceability/acceptance report with starting/ending SHA, commands, environments, pass/fail/skip details and limitations.

### GUI-DONE-02 — Non-goals remain excluded

Do not add Reply/Quote, forwarding received LIVE, Delete for everyone, reactions, typing indicators, guessed presence, user avatars, rich link previews, cloud autocomplete, stickers/GIFs, group chat/PTT, file-transfer UI, payment integration, theme marketplace, extensive decorative animation, webview-based main UI or a transport-selection interface.

Do not rewrite Tor or create another general CLI. Do not add a second message/notification database or preserve stale development compatibility at the expense of a clean accepted contract.

### GUI-DONE-03 — Honest completion levels

Functional/design acceptance, installed desktop support and concrete hardware validation are separate evidence dimensions. The common GUI can be demonstrated on desktop while device integration is still unverified; that is not permission to claim the full appliance works.

A mandatory unresolved security/reliability behavior, missing approved layout, unsupported required platform path or unimplemented required public integration is an open gate. Document it precisely rather than silently dropping the feature, weakening a test or calling the task complete.

---

## Appendix A. Consolidation decisions and superseded ambiguity

| Topic | This version's authoritative resolution |
| --- | --- |
| CLI versus Terminal | Independent common CLI; UI wheels are optional separate distributions; Terminal owns only its own chat help |
| GUI naming | One `gui` frontend / `metor-ui-gui`; `embedded` is a deployment term |
| Missing `device.toml` | Desktop defaults when no config is requested; explicit bad/missing file is an error; no implicit disk search |
| Desktop versus simulator | Desktop is real normal use; simulator is explicit, contained and non-destructive |
| Exact layout | Deliberately delegated to the future approved companion, mapped to stable V/A IDs; no invented final pixel mockup in this file |
| LIVE tab | View change only; Start Live/Reconnect is explicit |
| Full duplex versus composer | Network/audio remain full duplex; this GUI temporarily hides/disables its own text composer during PTT |
| Draft restart policy | Preserve original disposable GUI drafts; Core generic recoverable drafts remain available to other clients; owner-qualified cleanup is required |
| Interrupted LIVE producer | Accepted LIVE bytes remain Core-owned and recoverable; not swept as uncommitted DROP staging |
| Voice consume | Inventory/placeholder/download is not consumption; explicit safe finalized playback handoff/release and no false skipped-audio claim |
| Delivered Voice resend | Only with complete authorized available source; new DROP ID; no persistent shadow LIVE recording |
| Auto-play recovery | Same logical context survives transport recovery; runtime loss resets UI override; foreground acquisition mid-turn does not auto-play old audio |
| Notification Off/count | No hidden events/history; current-state refresh after unlock; exact since-lock count only from actually received permitted facts |
| Lock | Per-client Core restriction, not a hard global profile lock or OS-lock claim |
| Purge authorization | Adopt latest Refactor-2 D01 scoped lifecycle capability; no anonymous cold purge and no restored obsolete Boolean bypass |
| Purge completion | Actual combined power-off-safe milestone; EOF/process exit alone is insufficient |
| Close versus Power off | Desktop close detaches this GUI; appliance shutdown is explicit, authorized and locally prepared |
| Pins | Protected profile-scoped peer metadata, not device TOML or a global plaintext sidecar |
| Fallback wording | Locally queued/converted, never automatically remotely delivered |
| Delete/clear | Local DROP only; pending delivery is preserved, so conversation can remain |
| Implementation sequence | Accepted Refactor 2 + final functional spec + approved layout, then vertical slice and full implementation |

These choices replace inconsistent earlier alternatives in place. Do not append a contradictory older clause as an extra requirement.

## Appendix B. Coverage of the original 75-section GUI specification

| Original section(s) | Coverage in this successor |
| --- | --- |
| 1–2 Purpose/principles | 0–1 Authority and product decisions |
| 3 Hardware model | 3 Startup/modes, 9 Input, 20 Platform |
| 4 Root architecture | 7 Logical root and view inventory |
| 5 Root DROP | 7 DROP membership/pinning; 8 contextual flows; 12 clear semantics |
| 6 Root LIVE | 7 LIVE lifetime/order; 8 explicit Start flows |
| 7 Peer selector | 7 Entry intent/tab switching |
| 8 DROP peer/text/Voice | 9–10 Composer/PTT/review; 12 DROP operations |
| 9–10 LIVE/PTT/full duplex | 8–11 Explicit actions, input and media |
| 11 Auto-play | 11 Eligibility/default/override and output priority |
| 12 Manual playback | 11 Incremental playback/timeshift/consume |
| 13 Timeline scrolling | 11 Scroll anchoring |
| 14 Route change | 8 Explicit lifecycle UI |
| 15 Recovery/fallback/resend | 12 Reliability presentation/status |
| 16 Incoming overlay | 8 Incoming-call flows; 14 locked actions |
| 17 Multiple LIVE | 7/11/14 Context identity, output and granted target |
| 18 Overflow | 10 Pressure; 12 local/remote typed reason |
| 19 Close/dismiss | 7 Local-only context retention; 8 eligible Core dismissal |
| 20 Notifications | 13 Complete volatile/privacy model |
| 21 Three independent policies | 14 Auto-accept/locked Accept/auto-play |
| 22 Screen/device lock | 14 Restriction/continuation/focus |
| 23 Unlock methods | 6 First-run setup; 14 authentication |
| 24 Incoming while locked | 8/13/14 Handle privacy and normal unlock |
| 25 Profiles | 6 Entry; 14 hidden name; 17 phase-aware transition |
| 26 Contacts | 15 Saved/discovered/rename/demotion/clear |
| 27 My QR/identity | 15 QR and address management |
| 28 History | 15 DROP versus projected/raw activity |
| 29–30 Settings | 16 Mapping/defaults/descriptors |
| 31 Notification sinks | 16/19 Safe optional metadata export |
| 32 Keyboard | 9 Input and keyboard modes |
| 33 Back | 7 Navigation; 9 capture-safe departure |
| 34 Power | 17 Desktop versus physical Power |
| 35 Purge | 18 Authorization/priority/true milestones |
| 36 LED | 13/14/18 Privacy and granted-media/arming feedback; 20 adapter roles |
| 37 UI restart | 4/5/10 Reattach and lifetimes; GAT-28/43/49/50 |
| 38 Daemon restart | 4 Epoch/state reset; 17 profile return |
| 39 Empty states | 7 View variants; 21 layout packet; GAT-01/69 |
| 40 Loading/startup | 3/6 Startup errors and authoritative bootstrap |
| 41 Errors | 19 Wording; 4 typed failure handling |
| 42 System events | 12 Typed actor/reason and privacy |
| 43 End Live | 8 Explicit end; 12 fallback policy |
| 44–45 Auto-fallback / Off | 12 Truthful outcomes and preserved pending |
| 46–47 Receipts/status | 11/12 Playback handoff and actual message facts |
| 48 Reply/Quote | 24 Explicit V1 non-goals |
| 49 Pinning | 5 protected metadata; 7 ordering/lifetime |
| 50 Destructive actions | 8/12/15/17/18 Scoped clear/remove/exit/purge |
| 51 Saved/discovered UX | 7/15 Core labels and Saved Contacts |
| 52 QR intent | 8/15 Intent-preserving flows |
| 53 PTT chronology | 9 Stable placeholder |
| 54 Composer exclusivity | 9 Full-duplex/composer resolution |
| 55 Voice buffer | 10 Admission/refusal semantics; 20 GUI bounds |
| 56 Locked LIVE versus Off | 13/14 Exact exception without unrelated notification |
| 57 Auto-accepted LIVE | 8/14 No automatic foreground/audio promotion |
| 58 Notification navigation | 13 Current-state reconciliation |
| 59–60 Isolation/storage | 4/5/16/17 Stable profile generation/protected GUI data |
| 61–62 Platform/simulator | 3/20 Explicit execution modes and technical ADR |
| 63–64 Theme/ergonomics | 19/21 Layout/accessibility/tokens responsibilities |
| 65 Screen inventory | 7 V01–V23 and required states |
| 66–67 State rendering/events | 4/9/14/17 Typed ordered models and lifecycles |
| 68 Terminal parity | 1/2/4/22/23 Same public semantics and regressions |
| 69 GUI-local features | 5/7/11/13 Presentation-state ownership |
| 70 Non-goals | 24 Explicit exclusions |
| 71 Scenarios | 23 GAT-01–30 corrected and retained |
| 72–74 Test/security/UX review | 21/23/24 Design and acceptance gates |
| 75 Definition of done | 22–24 Build, docs, traceability and evidence |

## Appendix C. Required handoff documents and source provenance

### C.1 Inputs for the next coding agent

The agent receives this file and the approved future `METOR_GUI_LAYOUT_SPEC.md`, plus access to the accepted post-Refactor-2 repository and its acceptance report. Earlier reviews and Document 1 may explain history, but are not substitutes for those three authoritative inputs.

The layout designer receives this file now and returns the companion described in section 21. Exact hardware dimensions and final screen arrangements come from that design/device input; toolkit/native integration details come from the bounded ADR work package.

### C.2 Source anchors used for consolidation

- Original GUI specification: [`docs/.temp/EMBEDDED_UI_SPEC.md`](https://github.com/DerWahreMirakulix/metor/blob/7804407593def11fcb6449f011bc92a9bc20e699/docs/.temp/EMBEDDED_UI_SPEC.md), immutable commit `7804407593def11fcb6449f011bc92a9bc20e699`, Git blob `8a0c5b73ff994f4e2f0cc54ee94ec2213d640bcd`.
- Historical first refactor: [`docs/.temp/CORE_TERMINAL_REFACTORING.md`](https://github.com/DerWahreMirakulix/metor/blob/7804407593def11fcb6449f011bc92a9bc20e699/docs/.temp/CORE_TERMINAL_REFACTORING.md).
- Provided later refactor handoff: `REFACTOR_2_CLI_UI_RELIABILITY_SPEC_7804407.md`, especially D01, WP4–WP10 and T24/T28. This is an assignment, not evidence it has finished.
- Provided earlier alternative handoff: `METOR_REFACTOR_2_SPEC.md`. Where its retained purge-Boolean wording conflicts with later D01, this GUI successor uses the stronger scoped-capability model explicitly stated in sections 0/18.
- Provided GUI reviews: `METOR_GUI_SPEC_REVIEW_2026-09-11.md` and `METOR_GUI_SPEC_REVIEW_AND_STARTUP_PROPOSAL.md`. Their alternatives are resolved by this document rather than carried forward as undecided suggestions.
- Owner decisions in this conversation: independent CLI; separate UI wheels; GUI ID `gui`; general help separate from Terminal chat help; GUI implementation after current Refactor 2; this functional document plus a future separate approved layout document as the implementation basis.

The artifact was authored as a specification, not by modifying repository source or executing GUI/hardware tests. New defaults, target launch options, input thresholds and resource baselines are normative decisions made by this consolidated version, not claims of already shipped behavior.

### C.3 Change log

**1.0 — 11 September 2026:** Consolidated the former Embedded GUI specification and post-refactor reviews. Separated functional and visual authority; froze startup/default/device-error semantics; adopted separate-wheel/common-CLI and D01 authorization boundaries; resolved tab navigation, composer, draft lifetime, media availability/consume, notification privacy, close/power and purge contradictions; supplied view/action IDs, technical-selection boundaries, layout deliverables, 75 acceptance groups and original-spec coverage.

---

**Implementation basis:** accepted Refactor 2 + `METOR_GUI_SPEC.md` v1.0 + approved `METOR_GUI_LAYOUT_SPEC.md`. No implicit product redesign while converting the design into code.
