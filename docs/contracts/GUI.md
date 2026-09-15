# Metor GUI runtime contract

**Implementation status: incomplete development vertical slice. Not release-ready.**
This is the current GUI entry point. The approved
[functional v1.0](../specs/METOR_GUI_SPEC.md) and
[layout v1.0](../specs/METOR_GUI_LAYOUT_SPEC.md) remain the implementation
authority; the copies preserve the exact input bytes. This document reports
implementation facts and does not weaken those requirements.

The owner paused implementation on 15 September. See the
[current handoff](../audits/GUI_IMPLEMENTATION_2026-09-12.md#15-september-pause-handoff--current-continuation-entry)
for source state, exact verification checkpoints, estimates and restart steps.
Installed-package evidence predates the final retained-root changes; those changes
need a fresh artifact build before final-source packaging acceptance.

## Current implementation

`metor-ui-gui` owns only `metor.ui.gui` and local visual assets. It depends on
matching `metor`/`metor-sdk`, Kivy 2.3.1, sounddevice 0.5.3 and qrcode 8.2.
It does not depend on Terminal. The launcher imports Kivy only after explicit
GUI selection and device-description validation. Application version remains
0.2.0; no release or tag is created. Schema 4 adds protected GUI metadata with
a transactional migration from schema 3; IPC 2 gains additive DTOs/capabilities.

The current slice includes graphical profile entry/create/picker and deferred
host prompts; a native responsive root and peer text composition; public SDK
bootstrap/snapshot and bounded DROP reads; volatile drafts; exact-ID send
duplicate barriers; and explicit non-destructive simulator mode. It does not
implement the complete V/A inventory. Protected settings and application lock
use protected preferences and Core restriction/reauthorization;
bounded notifications and exact pending-call handles are implemented; complete
settings/media acceptance remains open.

No GUI code imports profile storage, daemon or transport implementation modules.
Desktop close now waits for this GUI's capture finalization, requests owner
release, detaches its client and clears volatile references. It preserves shared
Core activity; only explicit profile switch invokes public normal exit/hard lock.
V20 provides a bounded local catalog, exact-target create/rename/remove/default
operations, full-password change and stopped-profile address generation/readback. Existing
Core identity keys are reused; the GUI explains this before requesting full
target-password authorization.
Switch uses actual phases, independent target credentials and complete hydration;
unknown preparation never automatically unlocks the old profile. V22 now observes actual Core destruction milestones through the original
initiating SDK connection, with distinct unconfirmed, safe and cleanup-failed
results. No physical purge trigger or host shutdown is bound. Peer views expose headset-qualified
PTT and exact-owner DROP review. Core owner leases, allocation journaling and interrupted LIVE
recovery are implemented and tested; GUI bootstrap registers its disposable owner.
Bounded PCM playback, manual output priority and foreground auto-play are implemented;
bounded foreground text handoff and archive pagination are implemented; the full
native media matrix remains open. Shared root/peer actions implement protected
pins, DROP-only cleanup, selective/bulk LIVE fallback and ended-context dismissal.
End/Cancel and Change route carry exact Core lifecycle qualifiers. Explicit Retry
finalization rechecks the original owner's accepted audio and never sends a DROP.
The PortAudio probe and synthetic-output tests are not full media acceptance.

Own delivered LIVE text and complete retained PCM can be explicitly resent as a
new DROP with a new ID. The contextual action rechecks source availability;
received LIVE has no forwarding action. Playback and resend lease complete
sources within the shared 16 MiB volatile cache. A lost resend reply reads the new
ID's receipt without repeating append or commit. A confirmed incomplete new
Voice draft stays unsent and offers explicit discard. Cache eviction, local
deletion or privacy teardown removes corresponding source availability.

Settings reads permitted Core descriptors and effective profile values. Editors
show scope, source and constraints, preserve unsaved input during updates and
reject stale saves. Advanced contains safe Core technical controls and explicit
content-free platform diagnostics. Activity history displays paged Core metadata,
including recording-off state; Raw activity history is an explicit Advanced
selection. Clear activity history confirms the full underlying profile ledger
and unused discovered-contact effects while preserving messages. Unknown saves
or clears recheck state without automatically repeating the mutation.

Saved Contacts and the intent picker now render at most 64 rows per page and
keep the native search field through snapshot refresh. Manage supports up to 128
explicit selected identities and one confirmed Remove selected batch. Removal
uses Core's exact peer guard and stops at uncertainty; saved metadata is read
before another batch. New contacts never join the captured selection. The
native contact QR was independently decoded from its unchanged framebuffer;
camera input remains unavailable with manual entry.

Uncertain DROP cleanup and LIVE fallback read only the original displayed
identities. Core returns receipt status and optional archive presence without
reading payloads. Only positive absence/conversion releases corresponding GUI
copies; later arrivals, other directions and owned Voice reviews are excluded.

## Development installation and launch

Use the existing repository developer environment, then:

```sh
python -m pip install -r requirements/gui.lock
python -m pip install --no-deps --no-build-isolation -e packaging/gui
metor chat --ui gui
metor chat --ui gui --simulator
metor chat --ui gui --simulator --device-config docs/examples/gui-simulator.toml
```

No requested file means desktop. `--device-config` overrides nonempty
`METOR_DEVICE_CONFIG`; explicit relative paths become absolute in the common
launcher. Invalid files do not fall back. Device flags on Terminal are usage
errors. All help paths run independently of toolkit/device/auth initialization.

Build through the canonical bundle machinery:

```sh
python scripts/build_release_wheelhouse.py --variant gui --skip-pip-upgrade
```

`gui` is an explicit development variant, also included in the canonical `all`
group and CI/release validation. Installed-consumer checks cover both UI removal
orders, and the installer validator requires all four bundles. Linux and Windows canonical ZIP installers and installed consumers pass, including
both UI uninstall orders. Final-source artifact hashes and remaining product
acceptance are recorded separately in the acceptance report.

For an already assembled native wheelhouse, the actual independent package can
be installed without source checkout/editable paths:

```sh
python -m pip install --no-index --find-links ./wheelhouse metor-ui-gui
```

Linux needs a working SDL2/OpenGL display and PortAudio for the candidate audio
port. Optional unavailable capture/output must not fabricate playback or
consume Voice. The tested environment offers SDL offscreen rendering and zero
audio devices on Linux. An isolated native Windows Python 3.11.9 runtime also
launched the installed GUI. A user-authorized Razer BlackShark capture/playback
probe passed. The native GUI also passed a short focused-key PTT/review test
against an actual temporary encrypted Core and Razer headset. This does not prove
physical-key input, acoustic quality, AEC, the full duplex matrix or unplug recovery.

## Everyday operation

Choose or create a profile on entry and complete its graphical authentication.
In Settings → Profiles, changing the selected profile uses its own credentials;
read the displayed draft/shared-runtime consequences before continuing. Address
generation is available for a stopped local profile only, requires its full
password, and reuses existing Core identity keys. After an uncertain result,
Check address performs a read instead of repeating generation.

DROP and LIVE select separate conversation projections. Selecting a tab or
opening a conversation does not call its peer. Use Start Live explicitly; Accept
answers the exact displayed incoming request, while Open only navigates to it.
Use Contacts for saved identities or Scan QR; when no camera is available,
manual entry preserves the original Save/Open/Start intent. My contact displays
only your public address/QR. Clipboard export is disabled.

Configure microphone/output and confirm the headset route in audio settings.
PTT records only while its original pointer/key is held; release finalizes that
turn. Losing focus stops capture and requires an actual release before another
press. DROP recordings offer Play, Delete recording and Send Drop separately;
recording or reviewing does not send them. Playback starts manually unless you
explicitly enable eligible foreground Auto-play. The waveform seeks audio;
Go live jumps to the available live edge, while the timeline's new-items control
only changes scrolling. Unsupported audio formats/routes remain unavailable.

More opens actions for the displayed item. Right-click, long press or focused
Shift+F10 reaches the same actions. Arrow keys move focus within conversation,
contact and DROP/LIVE groups; Enter activates. Resend is available only for your
eligible retained LIVE content and creates a new DROP. An uncertain operation
checks its original identity instead of silently submitting another one.

Lock covers private content using Core restriction and the configured policy.
Unlock restores current authorized facts. Closing the desktop window finalizes
this GUI's capture, releases its disposable ownership and detaches; it preserves
other clients' Core activity. It is not appliance Power off. Physical Power/PTT,
purge triggering and host shutdown are not yet bound to a supported appliance.
Simulator descriptions never gain real destructive or shutdown access.

## Contracts and evidence

- [Public integration map](GUI_INTEGRATION_MAP.md): actual SDK capabilities and
  unresolved security/reliability extensions.
- [Platform ADR](GUI_PLATFORM_ADR.md): native dependencies, framing and support limits.
- [Device schema](gui/device.schema.json) and [simulator example](../examples/gui-simulator.toml).
- [Support manifest](gui/support.json): renderer/install evidence versus untested targets.
- [Acceptance report](../audits/GUI_IMPLEMENTATION_2026-09-12.md): work packages,
  GAT/view/action coverage, exact checks, visual differences and open gates.
- [Frontend-neutral Core boundary](EMBEDDED_UI.md): still-current shared Core
  behavior; historical Embedded naming does not define another official GUI.

Assets and their license/revision/SHA-256 records live in
`src/metor/ui/gui/assets/manifest.json`. Native captures use synthetic identities
only. Installed operation performs no font/icon downloads, telemetry or update
checks. Clipboard export is disabled in composer and credential fields.

This code's RAM lifetime is not an OS secure-erasure guarantee. Hardened
swap/crash-dump/screenshot controls, screen-reader privacy, full keyboard/PTT
behavior, owner-loss media safety and every unimplemented GAT remain required
before production acceptance.
