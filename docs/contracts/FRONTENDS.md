# Frontend integration contract

This document defines the shared Core and SDK boundary for every Metor
frontend. The official frontends are `terminal` / `metor-ui-terminal` and
`gui` / `metor-ui-gui`. The [GUI contract](GUI.md) covers GUI behavior, device configuration,
presentation, and startup.

This contract does not define screens, navigation, playback, hardware drivers,
or other presentation behavior. Terminal, GUI, and third-party clients consume
the same typed boundary without gaining storage, transport, key, or host-process
ownership.

This frontend-neutral contract owns public integration behavior. GUI-specific presentation belongs in [GUI.md](GUI.md).

## Ownership boundary

- Core owns profiles, identity, contacts, message identity, DROP/LIVE semantics,
  persistence, ACK/dedupe, transport recovery, fallback, authentication,
  resource limits, and typed runtime facts.
- `metor.client` owns IPC connection/bootstrap orchestration and the safe profile
  transition coordinator.
- A frontend owns navigation, focus projection, drafts, scroll and playback
  cursors, wording, notification presentation, and bounded volatile copies of
  already-consumed LIVE content.
- The platform layer owns capture/playback, echo cancellation, display, hardware
  input, LEDs, haptics, camera, and physical power control.

Frontend-independent, typed local platform contracts live in
`metor.client.platform`. Hardware status, ordered input observations and
capability-specific controlling actions are separate interfaces, not a shared
notification hook. See the canonical
[platform ownership decision](../ARCHITECTURE.md#frontend-independent-typed-platform-contracts).
These local contracts neither add IPC authority nor make an untested adapter a
supported appliance.

`PlatformBindings` is the frontend-neutral composition object. It keeps status,
input and each actuator as separate ports and carries one bounded registered ID.
An appliance owner may inject it through `FrontendLaunchContext`; the GUI accepts
physical mode only when strict configuration names the same ID. Simulator mode
rejects all physical bindings. Optional actuator ports remain unavailable unless
their matching configuration tables explicitly select that ID. Before normal
power the GUI rejects remote ownership and another running local profile. A
shutdown port must atomically enforce its own local privilege and exclusive
host/runtime ownership and is called only after the GUI has confirmed the
appropriate Core lifecycle boundary.

Opening a view is never a network action. A frontend must issue explicit typed
commands for connect, reconnect, fallback, accept, reject, disconnect, consume,
or dismiss behavior.

## Startup selection and invocation lifetime

The catalog, persisted default, requested `-p` name, initial selection and
authenticated active profile are separate facts. `FrontendHost.initial_selection()`
returns one bounded `FrontendSelection` with a typed kind (resolved, choice
required, empty, requested missing, or unavailable), requested name, resolved
name and valid stored default. It is an explicitly requested initial resolution;
paginated `profile_catalog()` reads never repair a default. The general CLI loads
any installed frontend and passes the host without profile-dependent UI-name
exceptions. GUI renders create/picker/error routes; Terminal currently prints
selection guidance and exits before chat/daemon startup. A future Terminal picker
can call the existing host `select_profile()` and then `bootstrap()`; no picker
is currently provided. Host selection revalidates each chosen profile at the
activation boundary. First successful creation sets the default. A stale
or missing default resolves to the sole valid profile; several profiles without
a valid default require a choice. Rename follows the default; permitted removal
reconciles it to the sole survivor or clears it when none remain. Empty storage
has no synthetic selected profile. Syntactically valid missing or damaged names
are reported safely, and explicit `-p` never changes the persisted default.

The common `FrontendHost` evaluates ASK, ALWAYS and NEVER only when the selected
profile is activated. GUI interactions are graphical even when launched from a
shell; Terminal prompts before chat. A remote profile never triggers local daemon
spawn. Each chat invocation retains the exact local daemon process it spawned
and stops it at final close or when that profile is retired. An already running
local daemon is borrowed and is only detached. The child also observes owner
process disappearance so a lost parent cannot leave a session daemon running.

Cold encrypted unlock has a bounded initialization wait distinct from the
ordinary IPC request timeout. Frontends report failed bootstrap or lost
connection without claiming that an unauthenticated session succeeded. `--debug`
adds safe diagnostic locations; secrets and payloads are excluded.

## Attach and race-safe recovery

After the normal IPC version/auth handshake, a rich frontend must:

1. send `RegisterLiveConsumerCommand` so it receives typed asynchronous events;
2. request `GetRuntimeSnapshotCommand`;
3. install `RuntimeSnapshotEvent` as its projection baseline;
4. apply newer projection invalidations within the same epoch. Always process
   command outcomes, media and lifecycle control events independently of that
   projection revision filter.

Every IPC event carries the daemon-authored monotonic `revision`. The aggregate
snapshot contains profile and Onion identity, saved/discovered contacts,
content-free DROP conversation summaries, LIVE contexts, pending incoming
requests, unread and pending counts, disconnect reason, and settings revision.
It deliberately excludes message content and UI-only state.

The daemon also assigns a fresh opaque `epoch` at each start. Clients reset
revision ordering when the epoch changes. `RuntimeSnapshotUnavailableEvent`
means the bounded stable-read retries were exhausted and the request is safe to
retry; it is never an unchecked snapshot. The client IPC layer owns the only
socket reader, registers a request before writing it, demultiplexes correlated
responses, and queues unsolicited events within bounded capacity. Overload fails
the connection with one reliable loss notification requiring reattachment/resync;
it never silently claims complete delivery. A shared
`RuntimeStateChangedEvent` has no request correlation and invalidates only its
content-free scope for every authorized client. Connection and pending-request
events are absolute keyed upserts, not counters to apply more than once.
Snapshot composition validates both the publication revision and an atomic,
content-free state token. Reconnect grace and scheduled reconnect are explicit
states, distinct from terminal disconnect with a machine-readable actor and
reason.

## Messaging contract

The stable logical shape is `MessageContent + Delivery + msg_id`.

- `Delivery.LIVE` is ephemeral interactive content. It may use crash-safe Core
  spool state while unseen or awaiting ACK, but it is not chat history.
- `Delivery.DROP` is durable mailbox content retained until explicit deletion or
  configured shredding.
- `TextContent` and `VoiceContent` are members of the same typed content union.
- One Voice press is one logical message with one immutable `msg_id`; bounded
  chunks and resume offsets are transport/application details beneath it.
- ACK confirms durable peer acceptance, not that a person read the content.
  Remote read receipts are optional and default to disabled.

`FallbackCommand(target, msg_ids=None)` preserves Terminal's peer-wide fallback.
Supplying IDs selects an atomic subset of pending outbound LIVE messages. A
successful fallback preserves each `msg_id`, removes it from LIVE replay, and
promotes the complete content to DROP. A malformed, cross-peer, non-pending, or
already-promoted selection is rejected without partial changes.

`MarkReadCommand(target, delivery=None)` preserves the combined Terminal consume
flow. Rich clients should supply `DROP` or `LIVE` when projections are separate.
Only selected unread text rows are consumed; Voice has its own handoff contract.
`ClearMessagesCommand` and direction-qualified `DeleteMessageCommand` affect
only eligible local DROP presentation/payload state; an omitted direction is
rejected when inbound and outbound receipts share the same peer and `msg_id`.
Pending DROP delivery and all LIVE state remain intact.
`DismissLiveContextCommand` is the explicit cleanup action for a disconnected,
non-recovering LIVE context and is rejected while outbound pending LIVE content
still needs reconnect or fallback.

### Voice capture and transfer

A capturing frontend uses `BeginVoiceCommand`, zero or more
`AppendVoiceChunkCommand` calls with exact byte offsets and bounded Base64
chunks, then `FinalizeVoiceCommand` for the same `msg_id`. Core permanently binds
the turn to its begin-time target. Connection loss does not finalize it; recovery
resumes after the peer-confirmed offset. Text and Voice remain full-duplex.

For DROP Voice, finalize creates a non-visible `DRAFT`. The frontend must issue
`CommitVoiceCommand` to publish it or `CancelVoiceCommand` to shred it. Incoming
or retained Voice is read only through bounded `GetVoiceChunkCommand` /
`VoiceDataEvent` ranges. After a safe playback handoff, the client explicitly
issues `ReleaseVoiceCommand`; reads never consume content implicitly.

A newly attached frontend discovers retained identities with
`ListRetainedMessagesCommand`. Its opaque cursor is filter-bound and tied to a
stable inventory version; stale pages fail explicitly. Entries expose only safe
identity/status/media metadata, never bytes, text, previews, or storage paths.
Enumeration and range reads preserve unread/payload state. Terminal displays
finalized inbound Voice as metadata-only text, including a notice that playback
is unsupported there. Its bounded retained-inventory lookup does not retrieve
chunks, issue `ReleaseVoiceCommand`, or mark Voice read; `/inbox` retains its
text-consumption behavior. Playback and Voice release require a capable client
and an explicit handoff. Pending outbound IDs
also provide the public discovery path for selective fallback after restart.

Peer wire generation 3 separates `/ack` (LIVE text), `/drop_ack` (DROP text),
`/voice_ack <id> <offset>` (resumable progress), and
`/voice_commit_ack <id>` (terminal Voice durability). A sender retains every
Voice segment until the terminal commit ACK. Duplicate matching chunks and END
frames are idempotent; conflicting bytes or offsets are malformed peer frames.

Core applies finite profile-aware retained Voice and shared pending-LIVE count /
byte budgets transactionally across text and Voice. It emits typed pressure and
hard-limit events, finalizes the current turn at the hard boundary, stores each
chunk as one bounded append-only encrypted object, never rewrites older chunks,
and rejects new turns while capacity is full.
Finalized pending LIVE Voice follows the same reconnect and selective/automatic
fallback rules as text. Once a frontend consumes unseen LIVE Voice, Core may
shred its owned spool; the frontend may retain only a bounded volatile copy.

## Restricted client/session lock

`LockCommand` remains the hard profile-runtime lock: it releases database, Tor,
blob, identity, and key runtime state. It is not a device screen lock.

`RestrictClientCommand` restricts only its requesting authenticated IPC session.
Its immutable lock-cycle policy selects:

- `unlock_method`: `PIN`, `PROFILE_PASSWORD`, or `NONE`;
- an optional continued LIVE target and whether locked Voice is allowed;
- incoming acceptance policy: `ALL`, `SAVED_CONTACTS`, or `NONE`;
- notification privacy: `SHOW_ALL`, `ANONYMIZE`, or `OFF`.
- `device_lifecycle`, granted only to a session authenticated before restriction.

Restricted clients cannot read normal contacts/history/messages/settings or send
to arbitrary targets. Reject is permitted; accept and locked Voice are checked
against the fixed policy in Core. Other authenticated clients, including a
Terminal session, remain unaffected. An anonymized restricted client receives
no peer identity/saved-status disclosure, and `OFF` suppresses unsolicited
presentation metadata. Multiple anonymous incoming calls use distinct opaque
action handles so accept/reject and expiry remain actionable without disclosing
identity. Locked notifications never carry message content. Locked Voice is
limited to the fixed continued LIVE target independently of notification
privacy; unrelated or DROP media is never exposed.

Quick unlock stores a salted Argon2id-derived verifier, never a PIN or profile
encryption key. The verifier is itself a usable authentication credential and
must stay inside the profile protection boundary with owner-only permissions.
Proofs are bound to one-use challenges. Password retries share the daemon-wide
failure counter and cooldown, including after reconnect or PIN escalation. A
Forgot PIN action requests a fresh password-salt challenge without fabricating
a failed attempt. After three failed PIN
attempts in one lock cycle, only the profile-password proof can reauthorize that
session; successful password recovery restores PIN eligibility for the next
normal cycle. PIN never starts a cold or hard-locked profile.

## Profile lifecycle and power

`ProfileRuntimeCoordinator` is the client-layer profile-switch boundary. A
frontend may inspect the current snapshot and must finalize platform-owned
capture before switching. The coordinator then requests
`PrepareProfileExitCommand`, disconnects the old client, attaches/authenticates
the selected profile, and returns a fresh aggregate snapshot. Normal preparation
durably applies configured eligible fallback, does not wait for remote DROP
delivery, terminates LIVE sessions, and hard-locks the old runtime. When fallback
is disabled, pending LIVE data remains recoverable and is not auto-reconnected
on a later return.

Self-destruct is a separate emergency path. Hard-locked anonymous clients cannot
invoke it. A restricted client can act only when it was authenticated before
restriction and its immutable lock-cycle policy grants `device_lifecycle`. The
`daemon.self_destruct_requires_unlock` deployment setting defaults to `true`;
setting it to `false` does not create anonymous, cold-boot, physical-input, or
new-session authority. No GUI preference can bypass this rule.

Once Core accepts one operation ID, destruction preempts Voice finalization,
fallback, reconnect, outbox delivery, and ordinary notification work. Core
reports runtime release separately from persistent key-protection destruction.
`SelfDestructSafeEvent` is the combined selected-profile milestone for an
encrypted profile; cleanup follows and reports completion or a typed phase
failure. Initiation, keyslot removal, runtime release, EOF, timeout, or process
exit alone is not the combined guarantee. A platform shutdown still requires a
validated local binding and exclusive runtime coordination, and must follow only
the documented safe-plus-terminal result or bounded post-safe cleanup-loss rule.

Purge affects only the selected profile. Ordinary exit never purges: it converts
eligible pending LIVE text and Voice to DROP when fallback is enabled, otherwise
retains them as pending LIVE, does not wait for delivery, and does not recreate
an automatic reconnect intent when the profile is next opened.

## Public capability and failure map

| Requirement family                 | Public owner and contract                                                                                         | Failure and reconciliation rule                                                                                                                 | Primary evidence                          |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| Launch and graphical bootstrap     | `FrontendHost`, `FrontendInteractions`, `FrontendLaunchContext`                                                   | Typed cancellation, unavailable, missing-profile and retryable bootstrap outcomes; no terminal prompt or local substitute for a remote endpoint | GAT-31–42                                 |
| Runtime projection                 | `register_live_consumer`, `RuntimeSnapshotEvent`, `RuntimeStateChangedEvent`                                      | Epoch/revision ordering applies only to projected state; media, request results and lifecycle reports are reconciled by their own identities    | GAT-42–45                                 |
| Text admission and unknown outcome | `SendMessageCommand(local_acceptance=True)`, `TextAcceptedEvent`, `TextRejectedEvent`, `GetMessageOutcomeCommand` | Definite quota rejection is immediate; a lost result is checked by the original ID and never resent blindly                                     | GAT-01, GAT-30, GAT-46                    |
| Retained Voice                     | `ListRetainedMessagesCommand`, `GetVoiceChunkCommand`, `ReleaseVoiceCommand`                                      | Inventory/read are bounded and non-consuming; only exact eligible finalized handoff releases content                                            | GAT-43, GAT-52–55                         |
| Voice producer ownership           | owner-qualified register/release and Begin/Append/Finalize/Commit/Cancel                                          | Disposable DROP cleanup is owner-scoped; committed winners survive uncertainty; interrupted authorized LIVE retains accepted bytes              | GAT-10–12, GAT-49–55                      |
| Protected GUI metadata             | `GetGuiPreferencesCommand`, `SetGuiPreferencesCommand`                                                            | Profile-instance scoped, bounded and revision-checked; stale writes reject rather than merge over another client                                | GAT-61, GAT-67                            |
| Qualified LIVE controls            | Connect/Accept/Reject, qualified Disconnect/Retunnel, Fallback, Dismiss                                           | Attempt/context qualifiers reject stale controls; fallback is atomic and preserves IDs; dismissal refuses unresolved work                       | GAT-03–06, GAT-13–16, GAT-57, GAT-60      |
| Restriction and unlock             | Restrict/Reauthorize/ConfigureQuickUnlock and restricted-state projection                                         | Immediate cover; exact lock-cycle policy and call handles; failed restriction never becomes client-side success                                 | GAT-20–23, GAT-56–60                      |
| Contacts and activity              | typed contact validation/mutations and paged history metadata                                                     | Stable identity guards prevent stale rename/remove; pages are bounded and body-free; uncertain mutation uses readback                           | GAT-02, GAT-03, GAT-17–19, GAT-67, GAT-68 |
| Profile lifecycle                  | `ProfileRuntimeCoordinator`, optional public host profile management                                              | Phase-aware result distinguishes source-active from source-prepared failure; target credentials and callbacks never cross profiles              | GAT-24–26, GAT-62–64                      |
| Device lifecycle and purge         | frontend-neutral platform ports plus correlated SelfDestruct reports                                              | Physical input grants no authority; unconfirmed preparation or destruction never reaches shutdown                                               | GAT-27, GAT-40, GAT-65, GAT-66            |

All additions within the current IPC generation remain strict, registered, and
defaulted where required. Generated wire shapes and capability names are
authoritative; this table records ownership and failure semantics, not a second
schema.

## Privacy and compatibility rules

- Never derive behavior by parsing human-readable strings; branch on typed event
  classes/enums and structured fields.
- Never place message text, Voice bytes, or previews in runtime snapshots,
  notification metadata, or detached notification sinks.
- Respect `daemon.ephemeral_messages`, history retention settings, and
  `daemon.send_read_receipts` in every frontend.
- Treat Onion identity and `msg_id` as stable keys; aliases are mutable labels.
- Render unknown `MessageContent` variants safely. Terminal intentionally uses a
  placeholder for Voice and remains a text-oriented client.

The complete wire shapes and defaults are generated in
[API.md](../generated/API.md) and [SETTINGS.md](../generated/SETTINGS.md).
