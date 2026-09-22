# GUI public integration map

Implementation input: functional and layout v1.0 in `docs/specs/`. Starting
accepted checkout: `0cfa122a47c879106b86de9578439df6ffc10b7c`, branch `embeddedui`.
The owner supplied acceptance of this baseline. Historical closure reports are
not a second backlog. Neither approved input is edited by implementation.

The application/SDK version is 0.2.0; IPC 2 (minimum 2), peer 3 (minimum 3),
launcher 2, DB 4 (minimum 3; transactional 3 → 4 migration), keyslot/blob and derivation generations 1. Values come from
`metor.versioning` and `metor.client`. Generated references are produced by
`scripts/generate_api_docs.py`, `generate_settings_docs.py`, and
`generate_compatibility_manifest.py`.

The baseline `InitEvent.capabilities` advertises `text_content`, `voice_content`,
`voice_inbound_descriptor`, `voice_bounded_read`, `retained_message_inventory`,
`voice_resume`, `voice_terminal_commit`, `voice_draft_commit`,
`restricted_client`, `restricted_voice`, `device_lifecycle`, `runtime_snapshot`,
`runtime_epoch`, `runtime_state_invalidation`, and `runtime_lock`.
The managed runtime now additionally advertises `profile_instance_id` and
`protected_gui_preferences`, `local_text_acceptance`, and `message_outcome`.
These are additive IPC-2 capabilities.
Protected runtimes with a blob store also advertise `disposable_voice_owner`
and `interrupted_voice_recovery`.

| Requirement                         | Public boundary / owner                                                                                                                        | Baseline availability and failure contract                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | Evidence target                                                                                                                        |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------- |
| Owner platform clarification / PLAT | `metor.client.platform`; SDK-owned local contracts                                                                                             | Frontend-independent typed hardware status, ordered input, streaming audio and controlling-action ports are separate. `PlatformBindings` composes one validated ID without merging authority; the launch context injects it. Optional actuator ports require their matching config table. Expired facts become unknown; input gaps cancel held actions; actuator outcomes do not grant Core authority. GUI audio, cached status, input and lifecycle consumers use the contracts; no production physical driver is registered. | `test_platform_contracts`, `test_gui_device_lifecycle`, `test_gui_audio`, `test_gui_buttons`, `test_gui_playback`; 20 September report |
| ARCH-01–04, START-01–03, BOOT       | `metor.client.FrontendHost`, `FrontendInteractions`, `FrontendLaunchContext`; base host implementation                                         | Deferred bootstrap, list/select/create exist; typed bootstrap rejection. Optional device_config and simulator launch fields are now added with defaults.                                                                                                                                                                                                                                                                                                                                                                       | GAT-31–42                                                                                                                              |
| API-02 stable profile identity      | `RuntimeSnapshotEvent.profile_instance_id`, `GuiPreferencesEvent.profile_instance_id`; Core storage                                            | Schema 4 persists an opaque instance ID. Rename/database move preserves it; recreated storage gets a new identity.                                                                                                                                                                                                                                                                                                                                                                                                             | `test_gui_metadata`, GAT-24, 61, 62                                                                                                    |
| API-03 snapshot                     | `MetorClient.register_live_consumer`, `runtime_snapshot`; Core `RuntimeSnapshotEvent`                                                          | Epoch/revision and explicit unavailable event exist. Snapshot does not supersede media or operation results.                                                                                                                                                                                                                                                                                                                                                                                                                   | GAT-42–45                                                                                                                              |
| API-01 retained media               | `list_retained_messages`, `get_voice_chunk`, `release_voice`                                                                                   | Bounded, non-consuming inventory and reads; invalid cursor and typed media rejection.                                                                                                                                                                                                                                                                                                                                                                                                                                          | GAT-43, 52, 53                                                                                                                         |
| INPUT-01 / MSG-05                   | `SendMessageCommand(local_acceptance=True)`, `TextAcceptedEvent`, `TextRejectedEvent`, `GetMessageOutcomeCommand`, `MessageOutcomeEvent`; Core | Opt-in local LIVE text admission precedes peer IO. Quota denial is definite. Exact-ID receipt lookup reconciles a lost success without resending; absent receipt remains unknown. Existing non-opt-in ACK semantics remain. Bounded foreground text handoff reserves GUI capacity before exact Core consumption.                                                                                                                                                                                                               | `test_gui_security`, `test_gui_contract`, GAT-01, 30, 46                                                                               |
| VOICE-01–05                         | Register/ReleaseVoiceOwner, owner-qualified Begin/Append/Finalize/Commit/Cancel/GetVoiceChunk/ListRetainedMessages; Core                       | Disposable connection-bound staging, pre-write allocation journals, exact cleanup, positive commit reconciliation and retryable interrupted LIVE finalization are implemented. GUI bootstrap registers the owner; PTT/review/playback views consume the complete contract.                                                                                                                                                                                                                                                     | `test_gui_producers`, `test_gui_capture`, `test_gui_playback`; GAT-10–12, 49–55                                                        |
| DATA-03 / SET                       | `GetGuiPreferencesCommand`, `SetGuiPreferencesCommand`, `GuiPreferencesEvent`, `GuiPreferencesRejectedEvent`; Core/storage                     | Protected 64 KiB/128-pin namespace, strict DTO, revision compare-and-swap. Unlock-method/setup changes require full-password strength; missing PIN verifier rejects selection. Plaintext profiles reject metadata storage.                                                                                                                                                                                                                                                                                                     | `test_gui_metadata`, GAT-61, 67                                                                                                        |
| ACT-03–10                           | Connect/Accept/Reject/Disconnect/Retunnel, Fallback, DismissLiveContext; Core                                                                  | Snapshot projects exact recipient pending handles, accepted call continuity and LIVE context generations. Shared fallback/dismiss GUI and qualified End/Cancel/Change route are implemented and covered by native interaction fixtures.                                                                                                                                                                                                                                                                                        | GAT-03–06, 13–16, 57, 60                                                                                                               |
| LOCK-01–05                          | RestrictClient/ReauthorizeClient/ConfigureQuickUnlock; Core                                                                                    | Per-session restriction, anonymous handles, full-strength configuration, immediate cover and generation revocation are implemented and tested through enclosing GUI paths.                                                                                                                                                                                                                                                                                                                                                     | GAT-20–23, 56–60                                                                                                                       |
| CONTACT / HISTORY                   | Contact DTOs, `validate_contact_qr`, history DTOs; SDK/Core                                                                                    | Public validation/mutations, originating intent, stale-label invalidation, bounded selection and paged history are implemented.                                                                                                                                                                                                                                                                                                                                                                                                | GAT-02, 03, 17–19, 68                                                                                                                  |
| LIFE-01–04                          | `ProfileRuntimeCoordinator`, `runtime.device.PowerFlow`; host/Core/platform                                                                    | Phase-aware switch exists and desktop close only detaches. Injected-device V21 finalizes its owner, rejects remote or competing active local runtimes, confirms local `PrepareProfileExit`, disconnects, then requests the fixed shutdown port. Unconfirmed preparation never reaches the actuator, and the port retains atomic exclusive-host enforcement.                                                                                                                                                                    | `test_gui_lifecycle`, `test_gui_device_lifecycle`; GAT-24–26, 62–64                                                                    |
| PURGE-01–03                         | SelfDestruct events; Core plus `runtime.device`                                                                                                | Restricted use requires the prior-authenticated `device_lifecycle` grant and still obeys `self_destruct_requires_unlock`; hardware supplies no proof. Exact operation/profile milestones drive V22. Only combined Safe plus terminal cleanup, or the bounded post-Safe cleanup wait, permits one configured shutdown request. Initiated/EOF/individual milestones do not; a queued Safe installed after EOF starts the bounded cleanup wait rather than inheriting EOF as terminal.                                            | `test_gui_purge`, `test_gui_purge_observation`, `test_gui_device_lifecycle`; GAT-27, 65, 66                                            |

## Ownership and compatibility

Root presentation now projects only Core DROP membership, applies protected pin
ordering, and pages native rows in groups of 64. The additive defaulted
`DropConversationSummaryEntry.pending_count` exposes existing outbound receipt
truth without a storage or protocol-generation change. LIVE projection preserves
Core contexts and adds bounded, explicitly disconnected same-runtime transcript
rows with canonical LIVE priority and recency ordering.

`runtime.drop.DropActions` owns exact GUI mutation correlations for
`DeleteMessageCommand` and `ClearMessagesCommand`. Only acknowledged local
scopes discard the corresponding transcript/cache copies. Pending delivery,
other projections, and owner-qualified unsent review copies remain protected.
Unknown completion schedules a read-only snapshot and never automatically
repeats a mutation. Root, peer and Privacy confirmations share
`views.actions`; no frontend persistence access is introduced.
`test_gui_drop` passes both real encrypted Core integration cases, including
inbound/outbound ID collision and review/pending/pin behavior. Root projection
and uncertain-result tests pass independently in `test_gui_root`.

`runtime.live.LiveActions` uses existing selective/bulk `FallbackCommand`
and `DismissLiveContextCommand` transactions. Positive conversion keeps IDs
and reports locally queued DROP counts; it never claims remote delivery.
Disconnected close removes only acknowledged LIVE presentation/cache/drafts and
its auto-play override. Local-only close needs no network mutation; unresolved
outbound sends/capture prevent local dismissal. Four action tests pass, including
real Core atomic-selection and pending-preservation cases.

Real selective-fallback IPC exposed an existing decoder defect:
`Optional[List[str]]` rejected valid lists before reaching Core. The SDK now
unwraps a non-null optional value before applying its declared validator.
Collection shapes remain strict, including string-only ID lists; the declared
optional transport-state mapping also round-trips. This repairs existing IPC-2
fields and does not change their names, shape or compatibility generation.
The wire regression rejects dictionaries, nested arrays and numeric/Boolean IDs.

Native settings presentation is promoted to `views.settings`: the page owns
group composition and protected LIVE preference editors own their warnings and
choices. `widgets.SettingRow` composition is implemented in the settings widget
module with measured title/help/value geometry. An editor submits the protected
revision it originally displayed; it cannot combine an old document with a
new revision and overwrite another client's changes. The real two-client
settings regression retains the concurrent change and its conflict explanation.

The GUI owns only `metor.ui.gui`; SDK and base remain frontend-neutral, and the
Terminal wheel remains independent. Toolkit widgets, presentation models and
native adapter implementations form separate cohesive GUI subpackages. Public
local platform contracts are SDK-owned in `metor.client.platform`. No GUI import of base
profile/storage/runtime implementations is permitted. Narrow public extensions
must be classified individually; this task does not automatically bump any
compatibility generation or application version.

## Design inspection

Penpot MCP reached file `d8ac01df-6646-81d2-8008-9fb60724c80a`, name Design,
current revision 69. All five pinned page IDs match. The saved version
`METOR GUI v0.7 · shared spacing and optical alignment` exists, timestamp
2026-09-11T21:45:01.685Z. MCP can list versions but its documented historical
operation restores/replaces the shared file; implementation does not invoke it.
Current-board inspection is therefore comparison evidence, not proof that later
canvas bytes equal the pinned version. Written layout v1.0 is authoritative.
Inner V09A viewport was exported and inspected, excluding its screen card.
The v1.0 notification-selection, compact End Live and keyboard corrections apply.

## Protected metadata ownership and compatibility decision

Schema 4 adds `profile_metadata` with a stable opaque instance ID and a bounded
`ui.gui` document. An explicit transactional migration accepts schema 3. Export
preserves the source version so an un-migrated copy is never falsely stamped 4.
The SQL pool exposes its existing metadata repository to the managed runtime;
it retains the actual storage-protection mode and avoids reopening keys during
snapshot projection. GUI and SDK receive values, never repository objects.

`ProfileMetadataCommandHandler` owns strict policy/CAS behavior. Existing
oversized daemon/session modules receive only wiring and narrow authorization
queries; the new behavior is outside them. Authorization and persistence run
inside the accepted runtime operation fence. `RuntimeStateChangedEvent` with
scope `ui.gui` invalidates protected preferences without publishing their data.
The GUI exposes protected timeout, lock-method, keyboard and lock-privacy
preferences alongside safe Core descriptors described below. GUI preference,
media and typed device-consumer presentation are complete at the claimed support
level.
No application, peer or key-format bump is
implied; IPC fields/commands/events are defaulted additive extensions.

## Text admission ownership

`TextCommandHandler` was extracted from the 793-line network dispatcher as its
text admission behavior grew. The network dispatcher is now 750 lines and
retains Voice/lifecycle routing; the extracted handler reuses the same Core
transport, outbox and message stores. The LIVE router invokes an optional
requesting-client callback after durable admission and before peer IO. Existing
callers receive their existing events. New local outcomes are not broadcast to
unrelated clients. No extra delivery queue or peer-protocol change is introduced.

The SQL receipt owner exposes only delivery/status for a canonical peer, local
direction and message ID. Its public IPC projection contains no payload/path.
The GUI reconciles only positive retained receipt facts; absence is not a promise
that a peer never received a message. Text intents and checks are bounded and
volatile, and no failed/unknown send is automatically repeated.

Schema documentation now expands nested public dataclasses instead of showing
them as unconstrained objects. Existing wire validators were already strict;
this generator correction does not relax or change their accepted fields.

## Voice producer ownership

The focused `managed.producers` package owns connection leases, pre-write object
allocation and cleanup reconciliation. Schema 4's `voice_producer_items` stores
bounded claims and object IDs in the protected database. A claim precedes Begin,
and each object ID is journaled before `put_with_id`; failed receipt admission
or failed deletion therefore cannot erase the only cleanup inventory. Cleanup
tries both temporary and persistent classes to cover interrupted promotion.

Claims are limited to eight DROP peers and nine items per owner, one DROP draft
per owner/peer, and 256 claims/owners per profile runtime. Existing unqualified
recoverable drafts retain their semantics. They are excluded from a GUI's
owner-qualified review inventory; another connection cannot read or mutate
owned staging by replaying its token or guessing its message ID.

Disconnect, explicit release and ordinary runtime release revoke leases. The
existing daemon maintenance cadence retries failures; a fresh service has no
valid inherited leases and reclaims recorded orphans. A pending committed DROP
receipt wins over stale ownership bookkeeping. LIVE accepted bytes are frozen
through the existing Voice finalizer, with interrupted state retained on failure.
Inventory reports `producer_interrupted` and `can_retry_finalization`; an
authenticated client can explicitly retry using `FinalizeVoiceCommand` without
asserting an invalidated producer token. Purge fencing preempts normal recovery.

The existing oversized Voice/daemon modules were reviewed for extraction.
Substantial lifecycle/allocation policy is isolated in `managed.producers`;
Voice receives a narrow allocation callback and a canonical rehydration/finalize
hook because it already owns metadata and retained turns. Router/manager layers
only delegate these hooks. This adds no independent delivery engine or GUI
storage access. IPC changes are defaulted additive fields and capability-gated
commands; no peer, blob encryption or key derivation format changed.

Eight isolated real-IPC/SQLCipher/encrypted-blob tests exercise token isolation,
review collision, restricted-lock preservation, explicit release, actual IPC
disconnect, committed DROP survival, failure after blob write/before receipt,
retryable deletion, fresh service ownership and explicit interrupted LIVE
recovery. Re-created service ownership deterministically covers the GUI/Core
producer-loss contract without depending on an OS-specific process harness.

## Capture interaction integration

`LiveContextEntry.context_generation` projects existing Core logical context
identity without changing the active-only restricted authorization query.
`BeginVoiceCommand.context_generation` rejects stale/ended/pending-inbound
targets. `live_context_identity` advertises this extension. Retained inventory
also accepts an exact `msg_id` filter with peer/direction and owner qualification;
the continuation fingerprint includes that filter (`retained_message_identity`).

The public SDK Voice convenience methods accept optional owner qualification;
Begin also accepts context generation. Existing unqualified callers retain their
semantics. No new message ID is allocated during append/finalize reconciliation.

`runtime.voice` separates the pure press machine, a capture worker and volatile
review metadata. The input worker owns a fixed connection/target, uses complete
PCM samples, and reads canonical retained state before finalization. Unknown
append responses are reconciled without resubmitting the frame. The input port
can stop callbacks while a request is pending, independently of playback. Drain
is limited to five seconds plus the bounded in-flight SDK exchange; excess
unaccepted capture is discarded with explicit feedback. The SDK's request timeout
still bounds each finalization/reconciliation exchange.

Normal navigation stops the bound press. Application lock covers immediately,
then waits for the capture worker before restricting the same client. Failed
explicit LIVE finalization is marked before the attempt and retried by Core even
if the producer connection remains attached. No further append is admitted to
that interrupted turn. DROP review remains owned and hidden behind restriction.

Four deterministic press tests and four actual GUI-worker/Core IPC tests pass.
The worker tests use finite synthetic microphone frames, not native audio. Native
PTT widgets, route selection and review/playback are now connected to peer views.
The later checkpoint below distinguishes native synthetic input from an
explicitly selected capability-compatible native route and complete product acceptance.

DROP review mutations now keep their exact owner/peer/message ID and perform a
bounded read-only receipt check after an uncertain result. The real lost-commit
test exposed unchecked optional receipt enums; `MessageOutcomeEvent` now uses
the SDK's established `Optional` annotations, with a wire regression for invalid
status values. Unknown receipt absence continues to block a duplicate Send.

Native route enumeration is deferred to explicit user intent and a worker. Its
bounded typed result uses the GUI mailbox rather than an invented IPC event.
Endpoint selection remains volatile and requires explicit headset confirmation;
enumeration does not open the microphone or assert AEC. Settings offers separate
input/output selectors and explicit headset confirmation. Native acceptance
harnesses use the same bounded enumeration, reject wrong direction or unsupported
PCM, and distinguish verified source mode from installed-wheel mode.

`ProfileActivation` now owns deferred host bootstrap and profile creation. The
runtime coordinator delegates those operations and exposes one generation-checked
client-adoption method. This cohesion extraction reduced the growing coordinator
below the 500-line review threshold while preserving the same public host/SDK
flow and one-use credentials. No new storage or launcher boundary was introduced.

## Native peer input and playback integration

`views.peer` now owns a persistent pane and a separate input-stage composition.
Background results update existing message identities and controls; shell changes
only replace the pane on route, authorization or geometry transitions. The native
window observes key state before focused PTT dispatch and routes releases to the
original input owner after focus changes. Ctrl+Enter is fresh-key guarded. Native
SDL tests cover repeat suppression, focus transfer and repeated repaints using
synthetic input; they do not represent physical GPIO or acoustic evidence.

`runtime.playback` owns single-output arbitration, foreground/context auto-play
eligibility and an independent bounded output worker. `state.media` owns exact
activation-qualified targets, local output progress and the shared 16 MiB encoded
cache. Local progress has a typed mailbox field and is never represented as a
fabricated IPC event. The decoder reads at most the public 64 KiB range ceiling
and writes complete PCM samples in 20 ms frames. Source identity, direction,
delivery, offsets, encoded lengths and codec are checked before output. Native
output closes before any finalized inbound release request. A nonzero seek does
not count skipped content as played. Complete cached replay avoids re-fetching
positively released data; cache eviction removes replay availability.

Review playback uses the exact connection-bound staging owner and cannot commit
or consume the outbound draft. Application restriction waits for both capture
and playback workers after immediately covering the UI. Route/focus departure
revokes queued/output work, including reads that return after departure. Auto-play
queues only new eligible incoming starts, with a bound of 64; a new logical
context copies the protected default once, genuine recovery preserves its
override, and a stale queued start cannot cross context replacement.

`runtime.transcript` retains bounded plain text and Voice descriptors keyed by
peer, projection, direction and message ID. It does not persist LIVE history or
download audio merely to populate a list. Foreground handoff and page navigation
are described below. Large-item streaming, cache pressure and bounded worker
memory have dedicated integration/stress evidence.

## Bounded handoff, page navigation and local keyboard

`runtime.handoff` reserves the combined transcript count/byte budget before the
public text-only consume request. Every returned payload is installed into its
original peer/projection even if a normal application cover or navigation occurred
while the request was outstanding. No revision filter drops consumed content.
The additive optional Core bounds preserve legacy MarkRead callers.

`runtime.pages` owns single-page archive and inventory navigation, including
request serials invalidated on route departure. `ArchivePages` uses a public,
peer/direction-qualified exclusive boundary, keeps only one 64-row / 2 MiB page,
and provides Older and Latest navigation. `InventoryPages` uses the existing
non-consuming cursor contract for the current peer and delivery, with explicit
More and Refresh actions; stale cursors cannot be reused in another route.
The native timeline keeps at most 64 message widgets; page controls live within
its scroll content so opening the keyboard does not subtract another control row
from its minimum usable viewport.

The existing 500-line SQL history module was reviewed before adding paging.
Non-consuming archive projection moved cohesively into `data.sql.message.archive`;
consumption and deletion remain with `history`. The service manager adds only a
typed delegation, preserving facade ownership. Optional IPC fields/capability are
additive within IPC 2; no peer-wire or additional storage-axis change is needed.

`widgets.keyboard` owns offline key arrangement and modifiers; `views.input` owns
focused-field lifetime and docking. A public configuration method resets modifiers
between fields. Neither owner copies input into a history, suggestion model or
clipboard. The four-row keyboard is 264 logical units, with 48-unit PIN/special
keys and the approved narrow character-key exception. Native field traversal stops
at the self-parenting window boundary. Successful DROP review deletion/commit
discards its exact preview-cache identity and blocks late worker appends; terminal
LIVE state is ineligible for automatic new playback.

## Contact intent and native identity surfaces

`runtime.contacts.ContactFlow` owns a bounded nonsecret form, save/open/start
intent, exact response identity and read-only recovery after an unknown save.
Save-only returns to its caller; Save & Open Drop and Save & Start Live continue
only after a positive public result. Existing active/recovering attempts open
without another ring. A failed or unknown new call stays in its picker/form and
cannot automatically enqueue another request. An alias supplied inside remote
QR data never substitutes for the explicit local alias field.

`views.contacts` owns browsing/forms/identity presentation. Plain Saved Contacts
activation opens labelled actions; search is local, and removal/clear use explicit
confirmation. Rename and removal use the new optional Core identity guards;
unsupported guards disable those mutations. The 511-line contact service was
reviewed: the small guard stays with the existing identity lookup/mutation, and
no parallel frontend contact store was introduced. Rename/demotion broadcasts
replace labels using canonical identities, including offscreen form sanitization.
The discovered-peer cleanup test exposed correlated side effects; database
broadcasts now clear request correlation so they cannot terminate an unrelated
command exchange. IPC 2 remains additive, with no new storage or peer-wire axis.

`widgets.qr` renders the existing version-one public JSON encoding offline with
four quiet-zone modules, integer native module dimensions and a 240-unit ceiling.
`widgets.sheet` owns one revocable native modal and current-snapshot rebuilds.
Lock/purge revocation clears its labels before painting the covered shell. The
native input baseline now applies the bundled font and palette to all fields.
Contact multi-selection, camera-capable deployment evidence and the complete
hostile-label/resource matrix still require their enclosing acceptance work.

### Incoming calls and recipient authority

The GUI owns at most 128 content-free call entries, one explicitly selected
handle and one in-flight action. Its nonmodal surface does not call navigation,
recording termination or focus acquisition on arrival. Accept stays on the
current route; Open uses a fresh snapshot after acceptance or normal unlock.
No call-opening branch issues `ConnectCommand`. Decline uses the same exact
per-client handle, including after an anonymous Accept denial. Off suppresses
unsolicited presentation; anonymous entries retain neither alias nor Onion.

Core supplies the `pending_call_handles` capability and defaulted action fields
listed in the glossary. Snapshot and incoming-event source tokens are checked
against the original pending socket before the recipient handle is issued.
Final mutation still uses the existing atomic expected-socket removal. An
accepted call's optional `LiveContextEntry.call_handle` provides exact
navigation continuity across normal unlock, without extending restricted-media
permission or silently selecting a later call from the same peer.

Ownership rationale: the former 1,077-line session access module is now the
`engine/session_access` package. The same public facade owns the state; command
authorization, immutable restriction/proof lifecycle, event privacy and call
handle projection have cohesive implementation modules. Existing imports and
legacy command semantics remain valid. This is a Core access-control boundary,
not a second frontend authorization implementation. All additions are defaulted
IPC-2 fields; no incompatible IPC or peer-wire generation bump is required.

The shared action sheet now has a measured scroll body, fixed header/actions,
compact bottom placement, safe initial Cancel focus and privacy-cycle teardown.
The separate incoming surface intentionally uses native nonmodal composition.
Notification Center entries and clear watermarks are bounded volatile metadata;
Clear/Dismiss never invoke Core message, contact, read or lifecycle operations.

Pending-request operations were also extracted from the oversized network
connection-state module into `network/state/pending.py`. The shared coordinator
and its lock still own every socket, expiry and token; this changes module
cohesion without changing transport behavior or the network-state facade.

Outgoing LIVE text reserves independent transcript item/byte capacity before
submitting its public send. This reservation participates in the same aggregate
budget as capture metadata and foreground text handoff, and survives an unknown
result. It is released on definite rejection or replaced by the accepted exact
item. Early receipts update only that operation's known identity; later ACK or
metadata projections cannot downgrade known Read or Delivered. No local receipt
status creates Core delivery or read truth.

## Continued restricted media and privacy reconciliation

`GetRestrictedClientStateCommand` returns only the requesting connection's
current media grant and privacy-permitted call metadata. The GUI captures its
deliberate V09 target/generation before covering content; Core compares that
qualifier with its logical context before granting continuation. Restriction
from root, DROP or secondary views requests no media target. The GUI's
`runtime.security` package now separates authentication coordination from this
read-only continuation projection, preserving its original facade. This is
presentation ownership, never independent authority or a replacement client.

Core's network state distinguishes active transport and authorized recovery
from a fresh manual outbound call. `VoiceProducerService` remembers the original
admitted LIVE generation under its existing bounded owner lease. On terminal
context revocation, Core maintenance marks producer interruption and finalizes
the accepted prefix even while the IPC owner remains connected. Recognized
recovery does not trigger this reclamation. Existing durable commit-winner and
DROP-only disposable-cleanup rules remain authoritative.

Covered media uses the existing capture/playback workers, exact scope checks and
release barrier. Notifications Off still permits the separately granted media
strip; the strip shows no peer identity, includes accepted-time recording
feedback and reserves scrolling space for unlock controls. Auto-play remains
Off unless the original context override permits new incoming turns.

Accepted-call continuity also observes Core's exact pending-to-active socket
transition before privacy filtering. A second client's acceptance preserves the
original observer's navigation handle, without permitting stale Accept/Decline,
changing foreground focus or granting continued media to the accepted peer.

`InboxNotificationEvent` adds defaulted `delivery` and `source_id` fields. Core
projects kind-only anonymous activity and suppresses all such events under Off.
The GUI retains only a bounded kind cue while locked, with no since-lock count.
After normal unlock it refreshes current facts. Normal-session arrival hashes
distinguish new equal-count unread state from an unchanged cleared notification;
these hashes share the bounded notification metadata budget. The center has no
message previews, and neither its badge nor its clear actions consume messages.

These DTO additions remain additive within IPC 2. There is no additional DB,
peer-wire, launcher or cryptographic format change for continued media or
notification projection. Generated API/schema references are regenerated from
registered DTO sources.

## Exact call controls and finalization recovery

`DisconnectCommand` adds defaulted, mutually exclusive `context_generation` and
`attempt_id` qualifiers, advertised by `qualified_live_control`. Network state
owns current attempt tokens; delayed connect workers compare their captured
token before socket admission and cleanup. End/Cancel compares the caller's
original identity under the existing lifecycle lock and snapshot barrier.
`LiveControlCompletedEvent` and `LiveControlRejectedEvent` distinguish exact local
completion from stale intent without inventing a transport failure. Legacy
unqualified callers remain unchanged.

`RetunnelCommand.context_generation` and `qualified_live_retunnel` provide active
LIVE-only Change route. Core reserves route replacement before circuit IO,
rejects concurrent duplication and rechecks the original generation before
teardown. A replacement call survives a late rotation worker. Qualified calls
never fall through to cached DROP route operations. The defaulted snapshot field
`route_changing` supplies the actual progress/eligibility state. These changes
are additive IPC-2 contracts; other compatibility axes are unchanged.

Root and peer menus share these exact actions. Native End buttons retain the
context captured when created; replacement state creates a new control. Calling
shows Cancel without a new composer or Reconnect action. End waits for the GUI's
own original LIVE recording to finalize. `runtime.voice.recovery` owns explicit
Retry finalization: it reads exact owner-qualified retained state first, issues
at most one needed finalization, and only reads after a lost response. It never
resends captured bytes or commits a DROP review. The original held-input barrier
survives successful recovery. This extraction keeps capture recovery in the
existing Voice subsystem and does not add persistence or another media owner.

Ordinary remote lifecycle events coalesce an authoritative snapshot refresh.
They never navigate, and covered sessions use only the separately authorized
restricted projection. Core integration covers stale End/Cancel, delayed connect
and route workers, duplicate route admission and accepted-prefix recovery.
Native compact/wide synthetic-key probes cover replacement End identities and
calling Cancel, independently of Core or physical audio proof.

## Core settings and activity history

The shared config handler is promoted from `handlers/config.py` to the cohesive
`handlers.config` package. Its public `ConfigCommandHandler` facade is preserved;
`handler` owns command routing and `descriptors` owns the closed safe catalog.
Descriptors join the existing settings registry and effective profile configuration;
the GUI neither duplicates defaults nor imports configuration/storage internals.
31 permitted keys cover Live, Privacy, Voice buffer and Advanced quotas/timings.
SQL/Tor logging, plaintext modes, runtime mirrors and destructive authorization
policy are excluded. The external sink is not enabled by the GUI.

`safe_setting_descriptors`, `GetConfigListCommand.safe_descriptors`,
`SetConfigCommand.safe_only` and `expected_value` are defaulted additive IPC-2
extensions. Stale effective values fail under the profile config lock; global
values are untouched. `runtime.settings` owns finite descriptor readback and one
captured save. `views.settings.editor` retains unsaved input and focus across
snapshots, displays Core scope/source/constraints and closes on a positive save.
An uncertain save triggers readback, never an automatic repeat. Cover clears
descriptors and rejects late private reads. Receive Drops help explicitly states
that new Drop text sends and recording starts are refused when off; existing
finalized recordings may still be committed under the accepted Core policy.

`history_metadata_pages` adds opt-in `page_size`/`before_id` to existing history
queries without changing legacy limits or raw diagnostics. Core SQL retrieves at
most page size plus one rows, ordered by timestamp and ledger ID. The anchor is
checked in the same transaction. Free-form diagnostic text is excluded at SQL
selection; other scalar metadata is bounded. Projection scans only that page,
preserving the next raw anchor even when all rows are technical-only. Retention
flags come from current Core configuration. These additive fields do not require
another IPC, schema, peer or cryptographic compatibility-axis change.

`runtime.history` owns one 64-row metadata page, 128 finite cursor bookmarks and
one explicit history-clear operation. V18 shows summary metadata; Advanced opens
technical history and content-free platform diagnostics. Clear confirms the
entire profile ledger and unused discovered-contact cleanup. It does not clear
message payloads, saved contacts or notification-center state. Failed reads retain
the current page; an unknown clear only rechecks current metadata and remains
labelled unconfirmed. Cover discards identities; no substitute event log exists.
Settings/history scroll offsets are bounded volatile presentation state and are
discarded on cover/activation loss.

The native `InputDock` also owns the keyboard for an active `ActionSheet` field.
Modal keys are mounted above the native veil, tied to that exact field/sheet and
removed on departure. The sheet reserves keyboard height while keeping scope and
Save/Cancel outside scrolling content. This uses the existing offline keyboard;
it does not create another text buffer, input service or OS clipboard path.
Native synthetic touches reach the numeric keyboard through normal hit testing
at 360 × 640 / 150%, with the edited field and fixed actions above it.

Protected GUI preference saves retain the existing duplicate-action barrier
after an uncertain response. Only a successful same-profile, non-stale readback
releases it for a new explicit save. Failed reads preserve current values and
allow Reload preferences, never an automatic repeated mutation. The uncertainty
label remains after readback because current values alone do not establish which
client authored them.

Protected notification/display/input preferences use scoped setting rows. Their
fixed-choice sheets preserve the original document revision across snapshots;
disclosing more lock-screen information requires one explicit warning. The
timeout editor owns only its unsaved numeric input and captures the original
preference revision. Zero requires a distinct Disable lock confirmation; a later
edit resets that confirmation. A correlated positive save closes the editor,
while rejected/unknown saves retain input and provide explicit discard/readback.
`PreferenceBridge.save_serial`/`save_state` are volatile interaction outcomes,
separate from authoritative Core values and protected preference revisions.
The existing settings package owns these presentation modules; no additional
configuration store or permission authority is introduced.

The three real settings mutation tests cover two-client stale edits, denied unsafe
keys, actual Receive Drops scope and lost save responses. A separate late-read
privacy test rejects covered descriptor installation. Four history tests cover
equal-timestamp paging during arrivals, deleted anchors, technical-only pages,
diagnostic exclusion, retained Voice preservation and lost clear/read responses.
Native minimum-size/150% fixtures are renderer evidence, separate from Core tests
and physical hardware acceptance.

## Optional local profile-host extension

`metor.client` exports the pure `FrontendProfileManagement` companion protocol,
catalog, change request and action enum from its existing facade. The original
`FrontendHost` and launcher generation 2 remain valid; an older/custom host can
simply lack this optional interface. This is an additive in-process SDK contract,
not another IPC generation or a namespace migration.

`LocalFrontendHost` implements finite catalog pages, default selection, rename,
remove and create-without-selection through existing base profile services. The
selected profile is captured in each mutation and checked under the same host
boundary as bootstrap. Busy bootstrap fails safely instead of waiting on another
graphical prompt. Running/active/default removal and running rename obey the
existing base refusals. Exact profile-name validation occurs before GUI-host
selection/creation/mutation; arbitrary paths are not interpreted as names.

Creation from an active GUI retains the old host selection and consumes the
one-use secret even when busy or rejected. Original first-run creation continues
to select its successful result. Renaming a default profile updates its global
reference through an optional comparison in the existing locked `Settings.set`;
a newer default chosen elsewhere is preserved. Partial reference-write failure
reports the completed rename explicitly, allowing catalog readback without
blindly repeating the filesystem operation.

The host module was reviewed for cohesion before extension. It retains one
selected-profile/bootstrap boundary and delegates storage work to existing
profile services; the small comparison stays in the existing locked settings
write rather than creating another persistence owner. The SDK module contains
only the optional profile interface and DTOs. Six isolated host tests cover
bounded pages, exact selection, real encrypted creation, busy/running refusals,
invalid names, default-reference conflicts and partial rename outcomes. The
existing 30 settings contract tests still pass. The native V20 catalog now uses these services through a bounded worker mailbox.
Startup selection uses the same catalog without invoking a runtime transition.
GUI tests additionally cover actual rename with a lost host response, explicit
readback, worker-based startup selection and rejection of late covered catalogs.

## Profile and desktop lifecycle implementation (2026-09-14)

The GUI `runtime/profiles` package owns catalog interaction, active-profile
identity mutations and one covered lifecycle transaction. Native forms live in
`views/profiles`; neither package reads host files or owns persistence. This is a
cohesive package extraction because catalog, identity and transition have
separate state lifetimes within one profile-management subsystem. Ordinary
bootstrap and profile switch share the existing activation owner's SDK
connection, consumer registration, snapshot, staging lease and preference
hydration. No half-initialized target is installed.

`ProfileRuntimeCoordinator.switch(on_phase=...)` reports actual phases through an
optional observer. Observer failure cannot alter Core operation ordering.
`ProfileSwitchError.source_prepared` distinguishes confirmed Core hard lock from
socket release; a disconnect failure after preparation cannot imply A is active.
The previous `source_released` field and existing callers remain valid. This
additive SDK change needs no compatibility-generation bump.

`RuntimeSnapshotEvent.authenticated_client_count` is optional, defaults to None,
and reports the current authenticated IPC population, including the caller.
It is read under the existing session-access lock before taking the network
snapshot barrier, avoiding reversed lock order. This count is point-in-time
consequence metadata, not a guarantee that clients cannot attach later. Missing
count stays unknown. It adds no peer or authentication details and requires no
IPC-generation bump. The existing handler receives a narrow count callback;
no authentication ownership or substantial orchestration moves into it.

V20 captures each selected profile and shows one relevant active/pending/call,
local-draft and shared-client consequence confirmation. Actual source preparation
uses the public coordinator. It stops new input and waits for the original
capture worker, then releases only this GUI's staging owner. Source preparation
preserves Core reliability and hard-locks A. Target credentials use a fresh bridge;
source callbacks are fenced, and complete target hydration precedes publication.
Preparation uncertainty never triggers another preparation or automatic unlock.
Failure after A locks leaves explicit profile entry, not a claimed rollback.

Desktop native close and Settings Exit Metor share V21. They do not request
PrepareProfileExit, hard-lock Core, end another client's LIVE activity or invoke
host shutdown. Idle close needs no confirmation; disposable draft loss gets one
precise confirmation. The GUI remains responsive during finalization and owner
release. The 65-second capture-wait ceiling permits the five-second local drain
plus up to four default 15-second SDK waits. Expiry is unconfirmed preservation,
never success; only the advertised protected owner-loss contract enables the
explicit Exit anyway choice. Injected appliance power is implemented separately
in `runtime.device`:
V21 confirms Core preparation before the fixed shutdown port. Desktop exit keeps
the semantics above. A second active local profile refuses preparation, and the
configured shutdown port retains atomic exclusive-host enforcement. No production
driver is registered or claimed; its future physical proof is a separate support
dimension rather than unfinished GUI behavior.

Password change uses `ChangePasswordCommand` with the actual full current
password, replacement and local confirmation. Masked fields clear at admission;
command references clear after the one request. Rejected/unknown outcomes do
not claim a password change. Address rotation submits the existing operation
only after an effects confirmation and obeys the existing running-runtime refusal.
The GUI does not stop Core to bypass it; stopped-runtime rotation is exposed
through the public host operation described in the later profile checkpoint.

Eight lifecycle tests pass against public SDK orchestration and temporary
SQLCipher Core runtimes: GUI-only close preserves another client's LIVE socket,
old-lock/target failure, lost actual preparation receipt, capture uncertainty,
full-password verification, and a successful two-profile switch with independent
credentials and stale-callback rejection. The native 360x640/150% profile editor
checks original target/selection, focus preservation and rejected name retention.
These focused results do not complete device power/purge or full GAT acceptance.

The subsequent password-authentication regression exposed a pre-existing Core
gap: password rewrap left the old active session-proof verifier installed. Core
now derives the candidate verifier before changing storage and replaces it only
after successful rewrap, using the existing session-access owner. Rejected
candidates are cleared. Existing authenticated clients retain their sessions;
new sessions must prove the new password, and stale proof challenges/grants are
retired by the existing context-installation boundary. No auth policy is enabled
when session authentication was disabled. This is a correction to the existing
password operation, with no wire/storage/derivation-generation change.

Both real password tests pass (32.331 s), including old-password rejection and
new-password authentication after the actual change. The generic producer test
fixture uses a two-second request limit, shorter than the measured 2.432-second
verifier derivation. These password tests therefore instantiate the public SDK
with its production default timeout; security assertions are unchanged. The
accepted daemon password-change regression also passes (1/1, 0.003 s). The
612-test full checkpoint predates this correction. The existing daemon method
keeps this small orchestration step beside password rewrap; authentication and
secret clearing remain delegated to existing owners rather than a GUI authority.

## Delivered-own-LIVE resend and root recency (14 September)

`runtime/resend/` owns one volatile explicit new-DROP intent, its immutable
source/connection and its newly allocated ID. This is GUI interaction ownership;
Core still owns admission, producer staging, finalization, commit and receipts.
Text uses `SendMessageCommand`; Voice uses existing disposable-owner
Begin/Append/Finalize/Commit operations, with 64 KiB upload ranges. There is no
new wire operation, persistence owner, compatibility-generation change or LIVE
identity reuse. The cohesive package separates source eligibility, bounded upload
and outcome reconciliation instead of growing the capture or main controller.

Only own delivered/read LIVE content with a complete retained source is eligible.
Confirmed capture ranges can enter the existing 16 MiB cache; a finalization
receipt cannot fill a missing range. Complete-source leases prevent ordinary
eviction during playback/resend. Explicit deletion and privacy teardown still
revoke those sources. A lost resend result schedules one `GetMessageOutcome`
read for the new ID; no append or commit is repeated. A read-confirmed incomplete
new Voice copy remains unsent and offers explicit cancellation. Missing receipts
remain unknown. Simulator admission is explicitly disabled.

Six resend tests pass in 19.413 s against synthetic sources and actual isolated
encrypted Core IPC, including lost actual append/commit replies. Nine capture
regressions pass in 57.715 s, including confirmed own LIVE retention versus a
lost append acknowledgement. `tests/gui_native_resend.py` exercises actual native
Enter/repeat dispatch, open-menu eviction, received-LIVE exclusion and same-count
root invalidation at 360×640 and 150% text. This fixture has no Core, physical
input or audio IO; its image is an actual native framebuffer capture.

Core LIVE snapshot ordering now combines existing retained receipt update times
with Core-observed transport activity and uses canonical peer ties. The GUI keeps
active/recovering and pending/unseen priority above that order. Receipt queries
select metadata only. Small public manager methods delegate to the existing SQL
and transport state owners; neither manager gains a new orchestration subsystem.
No schema or protocol change is needed. Local rows now exclude own turns already
converted to DROP, and the native root invalidates from actual projected rows,
not merely the number of retained items.

## Scoped purge safety contract (14 September)

`purge_safe_milestone` adds optional exact-operation reports to the existing
authorized SelfDestruct command. The initiating client supplies a strict 16-byte
hexadecimal `operation_id`; Core retains it at its existing one-operation fence.
Repeated requests cannot change that identity or start another destruction.
Only the original recipient receives its correlated profile details. Existing
callers without an ID do not receive the two new event routes.

The central destruction owner now offers runtime-released and combined-safe
callbacks. Every existing independent release/key attempt still runs even when
an earlier step fails. `SelfDestructRuntimeReleasedEvent` requires all runtime
release prerequisites; `SelfDestructSafeEvent` additionally requires persistent
key destruction and is emitted by the managed daemon only for encrypted storage.
File cleanup occurs afterward. Failed milestone delivery remains unknown to the
client; neither key removal nor terminal/EOF alone substitutes for the safe event.
No new credential, anonymous cold grant, policy Boolean bypass, host power call,
profile recreation or destruction-status endpoint is introduced.

Five tests pass in 28.293 s: independent prerequisite failures, strict operation
identity, actual managed encrypted-profile destruction, actual runtime abort
failure and post-safe cleanup failure. Only isolated temporary profiles were
destroyed; an unrelated fixture file remained intact. Hardware-chord composition,
validated local lifecycle ownership and shutdown gating are implemented through
the typed platform boundary. No concrete physical shutdown adapter is claimed.
This is an additive IPC-2 contract; there is no storage, peer, keyslot, blob or
derivation change. The lifecycle mixin owns report publication; the small daemon
dispatch addition only retains correlation at the existing authorization/fence
boundary and does not add a competing destruction owner.

## Exact cleanup receipts and bounded contact management (14 September)

`MessageOutcomeEvent.archive_available`, advertised by `message_archive_state`,
is selected atomically with receipt delivery/status. It reports archive presence,
not cancellation of pending delivery or proof of non-delivery. The existing
two-value data `message_outcome` method remains compatible; the additive
`message_state` query supplies the richer IPC projection. No new persistence
schema, consumed content read, storage export or generation bump is required.

GUI `ReceiptReconciliation` holds at most 3,064 original metadata identities,
captured from existing finite transcript/cache/page owners before one mutation.
Each read yields to foreground work. Only exact positive DROP archive absence
releases a cleanup copy; exact DROP conversion reconciles an uncertain LIVE
fallback. Missing/failed/old-capability outcomes preserve copies. New arrivals,
opposite directions and owner-qualified reviews never enter an old batch. Four
DROP tests pass (28.568 s), and seven LIVE tests pass (28.619 s), including lost
actual mutation replies and preservation of unrelated items/pending work.

Contact orchestration is promoted into `runtime/contacts/`: `flow` retains the
existing public facade and intent behavior; `book` owns finite page/selection and
batch-removal interaction. Core still owns all saved identities and demotion.
Selection is capped at 128 identities/64 KiB captured alias metadata. One explicit
confirmation freezes the identities; sequential `RemoveContactCommand` calls
carry exact peer guards and stop at uncertainty. A `GetContactsList` read resolves
actual saved state before another batch; cover/exit stops further submission.
Six contact tests pass (19.229 s), including a real lost-first-reply batch that
preserves unselected and not-yet-processed contacts.

The native saved list/picker renders 64 rows per page; its search field survives
ordinary snapshot refresh. The 130-row native fixture verifies 64/64/2 pages,
selection across pages and exact search-focus retention at 360×640/150% text.
The native QR framebuffer independently decodes with zxing-cpp 3.1.1 and Pillow
12.3.0, installed only in a temporary validation directory. This is not camera
evidence or a production dependency. Reproduction uses `tests/gui_qr_decode.py`;
the upstream [Python decoder documentation](https://github.com/zxing-cpp/zxing-cpp/tree/master/wrappers/python)
defines that independent reader interface.

### Playback coverage ownership and paused continuation

`state.media` was promoted to a cohesive package with a thin facade preserving
`MediaCache`, `PlaybackTarget` and `PlaybackProgress` imports. Models, encoded
cache and bounded drained-output coverage have separate responsibilities. Coverage
is volatile, target/activation-qualified and independent of source byte eviction;
only successful output drain adds ranges. Fragment pressure loses knowledge
conservatively. No IPC/schema/compatibility change accompanies this extraction.
At this historical checkpoint, `platform.buttons` owned deterministic physical
state/timing arbitration only; it granted no authorization and had no registered
driver or shutdown effect.
The current evidence and outstanding work are recorded in the
[14 September pause handoff](../audits/GUI_IMPLEMENTATION_2026-09-12.md#14-september-pause-and-continuation-handoff).

### 15 September resumed implementation

The earlier work is committed at `85b4610` on `embeddedui`. Own delivered LIVE
text/Voice timeline rows now expose the existing exact-target resend menu;
native Enter/held-repeat and source eviction checks cover that actual entry.
Contacts now offer Scan QR while retaining save/open-DROP/start-LIVE intent
through the unavailable-camera/manual fallback.

The native Voice card now has a distinct keyboard/pointer audio-position action
and real PCM amplitude summaries. `widgets.voice` became a cohesive package with
card and waveform rendering behind its unchanged `VoiceCard` facade. `state.media`
owns finite PCM envelopes (64 coarsening bins per retained source) and indexed
chunk offsets, so replay seeking does not scan all preceding chunks. Rendering
never downloads or consumes Voice. Unknown samples are not fabricated; source
removal also removes its amplitude summary. These GUI-only changes add no wire,
keyslot, DB, derivation or application-version change.

Focused playback tests pass (13 tests), including actual sample peaks, bounded
coarsening, exact seek bytes and coverage/drain failures. Native 360x640/150%
resend/seek fixture passes with explicitly synthetic audio and no Core connection;
it uses real native controls and exact PCM seek offsets. Evidence filenames begin
`metor-native-resend-20260915` in the audit asset directory. This does not establish
physical audio or complete layout acceptance.

Existing `TorManager.generate_address` retains existing identity keys because
`KeyManager.generate_keys` is intentionally create-if-missing. Functional v1.0
GUI-CONTACT's identity rule explicitly requires Core's actual preconditions and
effects. A new cryptographic rotation transaction is therefore not an additional
GUI requirement. The optional public offline host operation exposes the existing
Core behavior, with explicit full target-password verification, running/remote/
stale-selection refusals, unchanged GUI host selection and read-only checking.
The profile form explains identity reuse and does not promise migration of old
conversations. Earlier shorthand referring to a mandatory new rotation transaction
must not be treated as a competing implementation backlog.

`FrontendAddressManagement.profile_address(FrontendProfileAddressRequest, OneUseSecretProvider)`
is additive and optional. The request captures target, original selection and
generate/read intent. `FrontendProfileOperationResult.onion` is an optional public
address field with a default; existing hosts/results remain valid. The base
`application.frontend` module was promoted to a host/settings/identity package,
with the unchanged public host factory and class behind a thin facade. Existing
test injection paths migrated to the host implementation. The GUI still accesses
no profile paths, Tor or private keys. The existing Core address generator now
cleans its own attempted Tor startup in a finally block, including failed startup;
a running-runtime refusal does not enter that cleanup path. This small lifecycle
correction stays in its existing cohesive owner; no broad Tor refactor is needed.
No wire/DB/keyslot/derivation generation or application version changes.

### Native continuity and bounded destruction observation

`views.root` now owns both root composition and canonical focus/pixel-anchor
continuity. Its thin facade preserves `root_view`; continuity retains keys and
coordinates, not another private widget tree. Peer and contact views are
reparented across the responsive breakpoint so native input/cursor, PTT binding,
selection and scroll state survive without a communication command. Root/contact
row and DROP/LIVE selector arrow groups move focus only; Enter activates.

`runtime.purge` isolates the new status observer from the already large
controller. The controller gains only admission/lifecycle delegation hooks.
A first matching Core milestone immediately signals producer cancellation and
then replaces the GUI with V22, clearing ordinary private state. A fixed-size
metadata channel retains only the original operation/profile/generation facts;
the existing initiating SDK connection is observed for a bounded interval.
There is no replacement connection, unlock, status reconstruction, owner-release,
retry, shutdown or new destruction command in this observer. A late event from
another operation or activation cannot retarget it. Initiated/EOF is unconfirmed;
combined safe destruction and failed file cleanup are distinct presentations.
Seven tests pass, including actual typed SDK events from destruction of an
explicitly temporary encrypted Core fixture. Six synthetic native V22 variants
also pass at 360×640/150%. This is not a production physical purge binding.

Context gestures on the actual message bubble, voice play control and waveform
use the same immutable target as visible More. Right-click/hold/Shift+F10 cannot
also play, seek or resend. Encoded cache fragments coalesce into bounded 64 KiB
blocks while public reads remain immutable; the playback suite now has 14 tests.
These changes add no IPC/schema/keyslot/derivation or application version bump.

### Root updates under continuous metadata load

The root package now separates page composition, identity-stable measured rows,
canonical menus and continuity. Existing rows update labels/counts/pins in place;
only inserted/departed identities allocate or remove rows. Callbacks capture peer
and delivery, not old aliases. A native 24-update fixture exercises real queued
arrow input while all 64 displayed rows change labels. A newly exposed selector
ancestor-walk loop was fixed at the native Window boundary. The root/menu facade
remains inside the GUI package; Core and IPC ownership/versioning are unchanged.

This extraction was chosen because frequent root snapshot refreshes must not
reconstruct the entire native control tree or retain stale aliases. The controller
stays unchanged. Native row/page tests still enforce bounded membership and
projection-only input, while the renamed-row fixture verifies actual focus and
pixel anchoring. Platform drawing latency is measured separately from Python
row-update time; a fast reducer alone is not a native responsiveness claim.

### Native accessibility and presentation ownership

The GUI owns `accessibility/{model,projection,native,bridge}`. AccessKit 0.7.0
implements native UIA/AT-SPI exposure; no Core/SDK message DTO, authorization,
launcher generation or storage axis changes. Its cross-thread boundary carries
immutable visible metadata and bounded requests, never Kivy widgets or profile
handles. The synchronous `GuiState.covered` fence clears native nodes, tooltips
and pending actions before the local cover assignment returns. Native requests
revalidate the current exact control on the UI thread. PTT cannot become a Click;
passwords supply no value/count; ordinary editor replacement is finite.

Native external clients verify reading, ordinary invocation and retained-node
revocation on Windows and Linux, with Windows normal-value replacement and Linux
editor focus. Full screen-reader product/navigation certification is separate;
the pinned Linux adapter does not expose the tested AT-SPI EditableText interface.
The adapter choice, startup/DPI order and isolated D-Bus test recipe are in the
[platform ADR](GUI_PLATFORM_ADR.md#native-accessibility-ownership).

Packaged DejaVu fallback selection and pointer tooltips remain GUI presentation
owners. They preserve canonical text and public action identity, add no remote
asset lookup and retain no private text in a process-wide lookup cache. Exact
license/coverage/icon bytes are checked against the packaged asset manifest.
