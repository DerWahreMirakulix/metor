# CORE_TERMINAL_REFACTORING.md

**Status:** Normative implementation specification for Agent 1
**Target:** Metor `embeddedui` branch / current pre-release codebase  
**Execution order:** This document MUST be completed before the Embedded UI implementation starts.  
**Language:** Code, API names, docs, generated docs, terminal strings, and later Embedded UI user-facing strings remain English.

---

## 1. Purpose

Prepare Metor Core, IPC/client contracts, persistence semantics, lifecycle/auth flows, and the existing Terminal frontend for the final Embedded UI.

This is **not** an Embedded UI implementation task. Do not build screens, touch layouts, HTML prototypes, software keyboards, notification-center UI, or device-specific GPIO/audio/display implementations here.

The goal is to leave a coherent, frontend-neutral Core contract that can support the finalized Embedded UI without the Embedded UI having to reproduce domain logic, infer state from strings, or work around missing events.

The implementation must preserve the existing Terminal frontend as a first-class client. Terminal behavior may be corrected where the current behavior is objectively wrong (for example a system-initiated overflow disconnect being reported as a local/user disconnect), but unrelated terminal functionality must not regress.

---

## 2. Pre-release rule: no legacy migration burden

Metor has **not had a public release yet**.

Therefore:

- Do **not** add schema migrations merely to preserve development databases.
- Do **not** add compatibility adapters for old local DB layouts.
- Do **not** preserve deprecated IPC shapes solely for unreleased external clients.
- It is acceptable to recreate development profiles/databases after structural schema changes.
- Tests and fixtures should be updated to the new canonical model.
- Generated API/settings documentation must represent only the new canonical model.

However:

- Existing **Terminal product behavior** is a regression boundary.
- Existing useful Core capabilities are a regression boundary.
- Stable semantic invariants such as message identity, deduplication, fallback behavior, contact demotion, history privacy, and secure destruction must be preserved or intentionally improved.

Do not confuse this rule with the existing user-facing `MigrateProfileSecurityCommand`. That command is a product capability for changing profile security mode, not a requirement to support obsolete development database schemas.

---

## 3. Architectural ownership

The existing ownership boundary remains normative:

```text
hardware/platform ports -> frontend -> metor.client -> typed IPC
                                                |
                                                v
                              daemon -> domain -> Tor/crypto/storage
```

### Core/daemon owns

- peer identity
- profiles and profile lifecycle
- lock/auth security state
- contacts and saved/discovered status
- DROP/LIVE delivery semantics
- message IDs and deduplication
- ACK state
- pending/outbox state
- reconnect/replay/fallback semantics
- persistent message state
- history
- settings
- resource safety limits
- typed facts/events needed by frontends

### `metor.client` owns

- framing
- request correlation
- protocol negotiation
- authentication exchange
- frontend-neutral attach/re-attach helpers
- frontend-neutral lifecycle orchestration where a single daemon IPC command is not the correct abstraction

### Frontends own

- visual presentation
- navigation
- scroll position
- transient drafts
- current visible projection
- local playback cursor
- transient/volatile notification-center presentation
- pinning/sorting preferences
- auto-play presentation preference
- UI wording

### Platform layer owns

- hardware input
- display
- audio capture/playback
- acoustic echo cancellation
- camera
- haptics
- LED/status indicator
- physical power control
- local device diagnostics

Do not move transport concepts such as `session`, `tunnel`, or `direct` into user-facing domain semantics. The user-facing message semantics remain **DROP** and **LIVE**.

---

## 4. Non-negotiable semantic invariants

These invariants must hold after all refactoring.

### 4.1 DROP vs LIVE

- `Delivery.DROP` means persistent/mailbox-style communication.
- `Delivery.LIVE` means interactive/ephemeral communication.
- Delivery semantics are independent of transport.
- A LIVE connection may coexist with DROP communication to the same peer.
- A DROP may reuse a live transport internally without changing its DROP semantics.
- Frontends must never need to choose a transport model.

### 4.2 Message identity

Every logical message has a stable `msg_id`.

- Replay/reconnect MUST NOT create a new logical identity.
- Dedupe MUST continue to use stable message identity.
- **Fallback of pending LIVE -> DROP preserves the same `msg_id`.**
- **Resend of an already delivered LIVE item as DROP is a new message and gets a new `msg_id`.**

### 4.3 No silent destructive behavior

Core MUST NOT silently:

- delete pending LIVE content,
- discard user-authored content because a UI navigated,
- convert content to DROP when the configured fallback policy is OFF,
- cancel pending DROP delivery as a side effect of clearing visible history,
- drop old voice chunks to make room for new ones,
- turn UI navigation into a network action.

### 4.4 Navigation is not networking

Opening a peer, switching DROP/LIVE projections, startup, unlock, UI re-attach, or viewing an old Live state MUST NOT implicitly:

- connect,
- reconnect,
- fallback,
- retunnel,
- disconnect,
- accept a call.

Network actions remain explicit Core commands/actions.

### 4.5 Privacy settings remain authoritative

No new Core or frontend feature may create a side-channel history that defeats:

- `daemon.ephemeral_messages`
- `daemon.record_live_history`
- `daemon.record_drop_history`

Notifications MUST NOT become a second message/history database.

### 4.6 Terminal remains a first-class client

Any shared Core/API change must be tested against Terminal.

Do not add Embedded-only branches inside Terminal. Shared semantics belong in Core/client; Terminal adapts only where the event/content contract changes.

---

## 5. Validated current state

The following current behavior has been validated against the `embeddedui` branch and should be treated as the starting point.

### Existing contracts already available

- `SendMessageCommand(Delivery.DROP|LIVE, TextContent, msg_id)`
- `ConnectCommand`
- `AcceptCommand`
- `RejectCommand`
- `DisconnectCommand`
- `RetunnelCommand`
- `FallbackCommand(target)` for all pending LIVE messages of a peer
- `AckEvent(msg_id)`
- `FallbackSuccessEvent(alias, count, msg_ids, onion)`
- `AutoFallbackQueuedEvent(alias, msg_id, onion)`
- `MarkReadCommand(target)`
- `ReadReceiptEvent`
- `ClearMessagesCommand`
- contact add/promote/rename/remove and saved/discovered semantics
- `ClearContactsCommand`
- projected and raw history APIs
- profile management APIs
- `LockCommand` / `UnlockCommand`
- session authentication challenge/proof
- `SelfDestructCommand`
- `GetChatStartupStateCommand`
- reconnect/retunnel lifecycle events
- `daemon.max_unseen_live_msgs`
- `daemon.fallback_to_drop`
- `daemon.auto_accept_contacts`
- `daemon.ephemeral_messages`
- `daemon.record_live_history`
- `daemon.record_drop_history`
- local auth attempt limit and cooldown

### Important current implementation facts

1. `FallbackCommand` currently selects a peer only; it cannot select specific `msg_id`s.
2. `MarkReadCommand` currently selects a peer only; it does not filter by `Delivery`.
3. Remote READ receipts are currently transmitted over the peer/live protocol.
4. There is currently no setting to disable sending remote read receipts.
5. `LiveMessageRouter.send_message()` may queue a pending LIVE message with no connection merely because `fallback_to_drop == false`, even when no real recovery is in progress.
6. Incoming LIVE backlog pressure already causes the receiver to terminate the Live session, but the local semantic disconnect actor/reason is not precise enough for the intended UI.
7. `ClearMessagesCommand` is not currently DROP-only; the underlying receipt deletion can affect LIVE state.
8. There is no single-DROP-message delete command.
9. There is no explicit safe command to dismiss/close a disconnected Live context and destroy its remaining inbound ephemeral state.
10. `MessageContent` currently resolves to `TextContent`; Voice is not implemented.
11. Existing startup state is chat/terminal-oriented (`active`, `contacts`, pending connections, unread summaries), not the complete aggregate projection required by the final Embedded UI.
12. The current Terminal frontend already:
    - sends LIVE while active,
    - buffers LIVE during its recognized reconnect/switch states,
    - uses `/fallback` as peer-wide fallback,
    - uses `MarkReadCommand`,
    - renders `ReadReceiptEvent`,
    - handles disconnect actor/origin/reason,
    - keeps some transient transport/send state in the frontend.
13. The current `LockCommand` securely releases the active profile runtime. It is a hard profile/daemon lock, not a smartphone-style screen/device lock.
14. `ProfileManager` is profile-specific. Existing `SwitchCommand` is peer/chat focus switching, **not profile switching**.
15. `NotificationService` is a dispatch service, not a notification history store.
16. `SelfDestructCommand` is destructive and must remain distinct from normal graceful shutdown/reliability flows.

---

# 6. Ordered implementation work packages

The work packages below are ordered deliberately. Complete them in order unless a dependency clearly requires a small preparatory change.

---

## WP0 - Baseline and regression harness

Before changing behavior:

1. Run the full existing test suite.
2. Run lint/format/type checks used by the repository.
3. Record current Terminal smoke behavior for:
   - connect / accept / reject / disconnect,
   - LIVE text send,
   - DROP text send,
   - reconnect/replay,
   - `/fallback`,
   - `/retunnel`,
   - `/inbox`,
   - contact add/remove/rename,
   - settings access,
   - profile auth/bootstrap.
4. Add/strengthen focused regression tests before changing risky behavior.

Do not begin the Embedded UI.

---

## WP1 - Correct message and fallback semantics

### WP1.1 Selective fallback by `msg_id`

Extend manual fallback so a frontend can convert either:

- all pending LIVE messages for a peer, or
- an explicitly selected subset.

Preferred contract:

```python
FallbackCommand(
    target: str,
    msg_ids: list[str] | None = None,
)
```

Normative behavior:

- `msg_ids is None` preserves current behavior: fallback all pending LIVE messages for the peer.
- `msg_ids` provided: fallback only those logical messages.
- Every selected ID MUST resolve to:
  - the same target peer,
  - outbound direction,
  - `Delivery.LIVE`,
  - `PENDING`.
- Validation must be atomic. Do not partially fallback a malformed/invalid selection.
- Successful fallback preserves the existing `msg_id`.
- Fallback atomically removes selected items from LIVE replay/recovery eligibility and promotes them to DROP.
- Existing `FallbackSuccessEvent(count, msg_ids, ...)` remains the success truth and should work for both bulk and selective fallback.
- A selected fallback initiated while reconnect/replay is running wins for those IDs. They must not later be replayed as LIVE as well.
- No duplicate DROP is created.

Terminal compatibility:

```text
/fallback alice
```

must continue to perform peer-wide fallback without requiring any Terminal UX change.

Add tests for:

- single selected text item,
- subset of several pending items,
- bulk fallback unchanged,
- invalid ID,
- ID belonging to another peer,
- non-pending ID,
- already-fallbacked ID,
- race with reconnect/replay,
- dedupe and stable `msg_id`.

---

### WP1.2 Reject new LIVE sends after terminal disconnect

Correct `LiveMessageRouter.send_message()`.

Required state machine when no live socket exists:

```text
real recovery is plausible
    -> allow durable pending LIVE

no recovery + fallback_to_drop == true
    -> convert/queue as DROP using same msg_id
    -> emit AutoFallbackQueuedEvent

no recovery + fallback_to_drop == false
    -> reject as LIVE
    -> DO NOT persist a new pending LIVE item
    -> emit a typed rejection/unavailable event
```

"Real recovery is plausible" means one of the existing genuine recovery states such as reconnect grace, retunnel, outbound/reconnect attempt, scheduled auto reconnect, or equivalent canonical state.

Do **not** use "fallback disabled" as a reason to accept unlimited disconnected LIVE sends.

Add a typed event for the rejected case. Name may follow repository conventions, but it must contain enough structured data for a frontend to associate the rejection with the peer and `msg_id`.

Terminal compatibility:

The current Terminal already normally falls back to DROP outside its LIVE/recovery states. Preserve that behavior and prove it with tests.

---

### WP1.3 Bound pending LIVE resources

Even after WP1.2, recovery windows can accumulate pending outbound data. Add defensive, profile-aware Core limits.

Required configurable limits:

- maximum pending LIVE logical message count,
- maximum pending LIVE retained bytes.

Use the existing settings/config framework and profile override conventions.

Requirements:

- defaults MUST be finite,
- no TTL-based silent deletion,
- no overwrite-oldest behavior,
- when the limit would be exceeded, reject the new LIVE item with a typed resource-pressure event,
- existing pending data remains intact,
- `0` / `-1` sentinel semantics should follow existing settings conventions where sensible,
- byte accounting must include future Voice payload retention, not just text string length.

This is a resource-safety control, not normal user-facing message semantics.

---

### WP1.4 Make conversation clearing DROP-only

`ClearMessagesCommand` currently affects message receipts without a Delivery filter. Refactor it so "clear conversation(s)" means **DROP only**.

Required behavior for all variants (`target`, global, `non_contacts_only`):

- remove only DROP conversation/history state,
- never remove or mutate LIVE unseen/pending state,
- never disconnect a LIVE session,
- never trigger fallback,
- never change a LIVE connection's lifecycle.

Pending outbound DROP delivery is delivery-critical state. Clearing visible history MUST NOT silently cancel it. Preserve whatever minimal/payload state is required to finish an already-authorized pending DROP, and keep behavior explicit in returned events/results.

Update docs to make the DROP-only meaning explicit.

---

### WP1.5 Add local deletion of one DROP message

Add a typed command for deleting one local DROP message by stable `msg_id`.

Suggested semantic contract:

```python
DeleteMessageCommand(
    target: str,
    msg_id: str,
)
```

Requirements:

- local deletion only,
- no "delete for everyone",
- no remote control message,
- target/message identity must be validated,
- only `Delivery.DROP` is eligible,
- securely remove local payload/archive state,
- preserve only the minimum receipt/dedupe metadata required to prevent unwanted redelivery,
- do not create a hidden copy in notifications/history,
- emit typed success/failure events.

Do not silently use this command as an outbound delivery-cancel primitive. If an outgoing DROP is still delivery-critical/pending, preserve delivery semantics or reject the delete with a typed reason rather than silently changing the send contract.

---

### WP1.6 Add delivery-aware read/consume

Extend `MarkReadCommand` with an optional Delivery filter.

Preferred contract:

```python
MarkReadCommand(
    target: str,
    delivery: Delivery | None = None,
)
```

Behavior:

- `delivery=None` preserves current Terminal behavior and consumes the peer's existing combined unread view.
- `delivery=DROP` consumes only DROP.
- `delivery=LIVE` consumes only LIVE.
- local consume/shred behavior remains correct for `ephemeral_messages`.
- the command must return/emit only IDs actually consumed by that filtered operation.

This is required so opening a LIVE projection does not accidentally mark DROP content read, and vice versa.

Terminal may keep using the omitted/default filter because the Terminal chat UX currently mixes the projections.

---

### WP1.7 Make remote read receipts opt-in

Add:

```text
daemon.send_read_receipts = false
```

Default MUST be `false`.

Remote READ receipts are optional UX metadata, not a reliability requirement.

When OFF:

- `MarkReadCommand` still works locally,
- local multi-UI unread state still works,
- ephemeral DROP shredding still works,
- ACK/dedupe/replay/fallback still work,
- NO `READ <msg_id>` peer frame is sent.

When ON:

- current remote READ behavior is allowed,
- the sender may receive `ReadReceiptEvent`,
- frontends may render a read state only when an actual receipt was received.

Receiving READ frames from a peer should remain supported for protocol compatibility even when local sending is disabled.

Terminal compatibility:

- Terminal continues to call `MarkReadCommand`.
- Terminal continues to handle `ReadReceiptEvent`.
- With the default setting OFF, Terminal simply sees no remote read event unless the peer chooses to send one.

---

## WP2 - LIVE lifecycle truth and startup projections

### WP2.1 Correct system overflow disconnect semantics

Existing behavior when `max_unseen_live_msgs` is reached is conceptually correct:

- the receiver refuses the new unseen LIVE item,
- it does not ACK it,
- the local side terminates the Live session,
- the sender is left with an unacknowledged item and applies its own fallback policy.

Keep that high-level behavior.

Correct the local event semantics.

Add a machine-readable reason such as:

```text
LIVE_BACKLOG_LIMIT_REACHED
```

The local peer that terminates because of its own safety policy must receive:

```text
actor = SYSTEM
reason = LIVE_BACKLOG_LIMIT_REACHED
```

It must NOT look like the local user pressed "End Live".

Do not leak the local buffer-limit reason to the remote peer by default. The remote peer may observe a normal remote session end/disconnect.

Terminal regression:

The Terminal currently treats `ConnectionActor.LOCAL` as an explicit user disconnect and changes focus accordingly. Update tests/handling so the corrected `SYSTEM` event behaves as a system disconnect, not as a fake user action.

Also ensure automatic idle-timeout/system terminations carry appropriate system actor/reason values where they currently do not.

---

### WP2.2 Add explicit close/dismiss for disconnected Live state

The user needs to explicitly destroy remaining ephemeral Live state after a Live connection has ended.

Add a frontend-neutral command for closing/dismissing a disconnected Live context.

Required semantics:

- valid for a non-active/non-recovering Live context,
- may destroy remaining inbound unseen LIVE content and Core-owned ephemeral receipts/state for that Live context,
- MUST NOT silently delete outbound pending LIVE messages,
- if outbound pending LIVE exists, reject with a typed reason and require the user to first reconnect or fallback those messages,
- MUST NOT perform fallback implicitly,
- MUST NOT reconnect,
- MUST NOT affect DROP conversation state,
- after success, the peer no longer appears in a Core Live-state projection unless a new Live-relevant state exists,
- orphan/discovered peer cleanup may run using existing contact/orphan rules.

This command is the Core half of the future UI's explicit "Close/Dismiss Live" action.

Already-consumed Live transcript content held only by a frontend is not Core state and is outside this command.

---

### WP2.3 Provide one authoritative aggregate startup/runtime snapshot

The final Embedded UI must be able to reattach after a UI crash without inferring state from strings or issuing an unsafe sequence of unrelated queries.

Promote/extend the existing projection work into one authoritative aggregate snapshot suitable for any rich frontend.

The aggregate snapshot must include at least:

- active profile/runtime identity needed by the client,
- saved contacts and enough peer identity to resolve renamed/demoted peers,
- DROP conversation summaries,
- DROP unread counts,
- active LIVE sessions,
- connecting/recovering LIVE sessions,
- pending inbound connection requests,
- disconnected but still relevant LIVE contexts,
- per-peer unseen LIVE count,
- per-peer pending outbound LIVE count,
- current connection/recovery state,
- relevant disconnect reason where available,
- settings/config descriptors or a stable reference/version allowing immediate settings hydration,
- current address/identity metadata required by normal UI bootstrap.

"Relevant disconnected LIVE context" means Core still owns one or more of:

- pending outbound LIVE,
- unseen inbound LIVE,
- other canonical unresolved Live state.

Do not include UI-only state such as:

- pinning,
- scroll position,
- keyboard visibility,
- local drafts,
- playback cursor,
- notification-center history,
- per-view auto-play override.

#### Snapshot/event race safety

Add an explicit state revision/sequence mechanism so a frontend can:

1. subscribe/register for events,
2. request snapshot,
3. receive snapshot with revision `R`,
4. ignore queued state events at or below `R`,
5. apply events after `R`.

An equivalent race-free mechanism is acceptable, but "best effort timing" is not.

Prefer adding an optional revision/sequence field to the common IPC event envelope/base so Terminal can ignore it without breaking.

Terminal may continue using `GetChatStartupStateCommand` if desired; do not force Terminal onto a richer UI-specific snapshot unless it reduces duplication safely.

---

### WP2.4 Notification/event hygiene

Do **not** implement a persistent notification center in Core.

Core responsibilities are:

- emit typed facts,
- provide precise actor/origin/reason,
- provide counts/IDs needed by frontends,
- never require a frontend to parse human-readable strings.

Do not add message text or voice content to notification metadata.

The existing detached `NotificationService` must remain a dispatch mechanism, not a history database.

Do not broaden external file/webhook notification payloads with message content as part of this refactor.

The future Embedded UI will build a bounded volatile notification projection from typed events.

---

## WP3 - Voice as a first-class content type

Voice is a required Core capability before the final Embedded UI can be completed.

Do not implement Voice as a completely separate messaging system. Voice must use the same high-level semantics:

```text
MessageContent + Delivery + msg_id
```

### WP3.1 Content model

Add `VoiceContent` to the typed content union.

One physical PTT press is one logical Voice turn and therefore one stable `msg_id`.

Do NOT create an arbitrary user-configurable "segment duration".

Logical model:

```text
one PTT turn
    -> one logical Voice message
    -> one msg_id
    -> many bounded transport/application chunks underneath
```

The user should not need to know chunk boundaries.

Design the blob/voice representation so future `FileContent` can reuse safe primitives where reasonable, but File transfer itself is not required by this task unless needed by the shared bounded blob foundation.

---

### WP3.2 Bounded authenticated/resumable chunk protocol

Implement application-level chunking above the transport.

Requirements:

- hard maximum chunk/frame size enforced by receiver,
- bounded indices/offsets and metadata,
- per-message `msg_id`,
- ordered/resumable transfer,
- integrity/authentication consistent with Metor's existing crypto/transport model,
- malformed chunk sequences are rejected safely,
- peer-supplied sizes are never trusted for allocation,
- a malicious sender cannot force an unbounded preallocation,
- receiver enforces its own local resource limits regardless of sender settings.

TCP/Tor packet boundaries are not the Voice resume contract.

---

### WP3.3 LIVE Voice lifecycle

Required sender flow:

```text
PTT down
    -> allocate msg_id
    -> begin one LIVE Voice turn
    -> capture/chunks arrive from frontend/platform
    -> stream chunks while connection is available
    -> retain enough local content/state for replay/resume/fallback

PTT up
    -> finalize the same logical Voice item
```

If the connection drops while PTT is still held:

- recording/capture may continue,
- the Voice item remains the same `msg_id`,
- chunks accumulate under resource limits,
- do not finalize merely because transport dropped,
- if recovery succeeds, resume from the missing/unacknowledged position,
- do not replay already acknowledged/heard chunks from the beginning.

If the frontend leaves the current Live context while PTT is held, the frontend will request finalization. Core must finalize that Voice turn without changing its target. A PTT turn is permanently bound to the peer chosen at PTT-down.

---

### WP3.4 Recovery and fallback for Voice

Voice must participate in existing reliability semantics.

If LIVE recovery succeeds:

- continue/resume the same Voice message.

If recovery terminates and `fallback_to_drop == false`:

- completed/finalized Voice remains pending LIVE,
- it can later be selectively fallbacked by `msg_id`,
- it can later be retried/reconnected,
- no automatic deletion.

If recovery terminates and `fallback_to_drop == true`:

- a Voice turn that is still being recorded MUST NOT fallback halfway through,
- wait for finalization/PTT-up or resource-limit finalization,
- then promote the **complete logical Voice item** to DROP,
- preserve the same `msg_id`.

Explicit selective `Send as Drop` of a pending Voice item:

- wins against replay/recovery for that `msg_id`,
- promotes the complete retained Voice item to DROP,
- stops further LIVE replay for the selected item,
- keeps the same `msg_id`.

Already delivered Voice -> DROP is **not fallback** and will later be implemented by the frontend as a new DROP send with a new `msg_id`.

---

### WP3.5 Full duplex

Core protocol and state management MUST allow concurrently:

- outbound Voice,
- inbound Voice,
- outbound Text,
- inbound Text,

within the same Live peer/session.

Do not enforce half-duplex in Core.

Echo cancellation, speaker routing, ducking, microphone gain, and actual playback mixing are Platform responsibilities.

---

### WP3.6 Voice buffer/resource policy

Add a configurable local Voice retention budget in bytes.

The budget is about **local resource use**, not a permission granted to the remote peer.

Requirements:

- profile-aware/configurable,
- finite default,
- exact value documented,
- no silent overwrite,
- no hidden auto-segmentation into new logical messages,
- emit typed pressure state at approximately 90% usage,
- emit typed hard-limit state at 100% / refusal boundary,
- a frontend can know when PTT must be disabled because no capacity remains.

For a local outbound LIVE recording:

- at the hard limit, finalize the current logical Voice turn cleanly,
- do not start a new Voice turn while the same physical press remains held,
- future UI will require PTT release before re-arming,
- if the total relevant Voice buffer remains full, reject new Voice starts until capacity is freed.

Capacity becomes free when retained LIVE Voice data no longer belongs to LIVE, e.g. after:

- successful completion/ACK and safe release,
- explicit fallback to DROP,
- appropriate state cleanup.

Once a pending LIVE Voice is safely promoted to DROP, it no longer consumes the LIVE Voice budget even if the DROP has not yet reached the peer.

For inbound Voice:

- enforce receiver-owned count/byte limits,
- never trust sender-side limits,
- on safety-limit breach terminate/refuse safely with a SYSTEM/resource-limit reason,
- do not leak detailed local quota policy to the remote peer unless an existing explicit policy setting permits such disclosure.

Protocol hard bounds such as chunk size are constants/protocol constraints, not user settings.

---

### WP3.7 Consume/unseen semantics for Voice

Voice must fit the existing LIVE unseen model.

- A background/non-consumed Live Voice item may be retained by Core under bounded policy.
- Once a frontend explicitly consumes it, Core may release/shred the Core-owned payload according to LIVE semantics.
- A frontend may keep a bounded volatile local copy for same-runtime replay; that is not Core history.
- UI restart is allowed to lose already-consumed Live transcript/playback data.
- Unseen/pending state must remain crash-safe as required by existing spool semantics.

Do not accidentally make LIVE Voice permanent chat history.

---

### WP3.8 Terminal behavior for Voice

Terminal does not need to record or play Voice in this phase.

It MUST, however:

- not crash when `MessageContent` is no longer Text-only,
- not access `.text` blindly for unknown/non-text content,
- render a stable placeholder/summary for Voice or unsupported content,
- continue handling text exactly as before,
- safely display inbox/history rows containing Voice metadata if such rows are queryable,
- remain forward-compatible with future content types.

A generic typed fallback renderer is preferred over Voice-specific crash-prone branches.

---

## WP4 - Core-owned restricted client lock and PIN quick-unlock

The final device needs smartphone-like screen/device lock behavior while the daemon/profile runtime continues to run.

Do NOT weaken or overload the existing `LockCommand`.

### WP4.1 Preserve hard `LockCommand`

`LockCommand` continues to mean:

- securely release the active profile runtime,
- cryptographic/daemon hard lock,
- normal communication capability ends until full profile unlock.

Do not change this semantic meaning merely to support a screen lock.

---

### WP4.2 Add restricted client-session lock

Add a frontend-neutral restricted IPC session state for a client that is "device locked" while the daemon remains active.

This restriction is per client/session; it must not globally lock other authenticated clients such as Terminal.

When restricted:

- normal contacts/history/messages/settings access is blocked,
- normal arbitrary sends are blocked,
- normal arbitrary peer switching is blocked,
- auth/unlock operations remain available,
- incoming call metadata/events may be delivered according to the locked-session privacy mode,
- selected locked-mode Live operations may be allowed only under explicit restrictions below.

This is a security boundary, not a frontend boolean.

A new IPC client created after a frontend crash must still authenticate normally; do not invent a persistent bypass merely to recreate lock-screen notifications.

---

### WP4.3 Optional PIN/quick-unlock credential

Add optional Core-managed quick-unlock/PIN support for an already running profile.

The profile password remains the root credential.

Required configured modes:

```text
PIN
PROFILE_PASSWORD
NONE
```

Semantics:

#### Cold boot / hard locked profile

- profile password is required,
- PIN cannot decrypt/start the profile.

#### Normal restricted device/session unlock

- use configured method,
- PIN may unlock/re-authorize the restricted client,
- PROFILE_PASSWORD uses the profile password,
- NONE permits immediate reauthorization according to the trusted client/session model.

#### PIN recovery

- "Forgot PIN" always falls back to full profile password.
- PIN reset/change/remove requires appropriate full authentication.
- PIN is not a PMK derivation credential.
- PIN is never stored in plaintext.
- Do not log PIN or PIN-derived secrets.
- Reuse the existing challenge/proof design or an equivalently strong local protocol instead of inventing unsafe raw-secret handling.

#### Wrong PIN attempts

- allow three failed PIN attempts for one lock cycle,
- after the third failure, PIN is disabled for that unlock,
- only the profile password may unlock,
- successful password recovery resets PIN eligibility for the next normal lock cycle,
- never auto-purge on PIN failures.

Integrate with existing auth attempt/rate-limit protections without weakening password protections.

Terminal is not required to expose PIN UX. It keeps using the profile password/session-auth flow.

---

### WP4.4 Locked Live permissions

Restricted session behavior must support the finalized device model without granting arbitrary unlocked access.

At the moment the client enters restricted lock, it may provide a locked-session policy derived from already-authenticated user settings.

Required policy concepts:

```text
continued_live_target: optional peer identity
live_while_locked: bool
accept_while_locked: ALL | SAVED_CONTACTS | NONE
notification_privacy: SHOW_ALL | ANONYMIZE | OFF
```

Once locked, the client MUST NOT be able to escalate this policy without authenticating.

#### Continued Live target

If `live_while_locked == true` and a Live peer was explicitly foreground at lock time:

- that one peer may remain the locked Live target,
- no automatic target switching,
- if that peer disconnects, do not promote another active Live peer,
- outbound locked Voice/PTT may target only that authorized peer,
- inbound Live audio eligibility for that peer can be supported by the platform/frontend,
- other Live peers remain connected/unseen but do not gain locked foreground privileges.

Core must enforce target scope; do not rely only on the UI not to send another target.

#### Incoming Live while locked

- `Reject` may be allowed without unlock.
- `Accept` without unlock is allowed only if the locked policy permits it:
  - `ALL`
  - `SAVED_CONTACTS`
  - `NONE`
- if policy does not permit acceptance, the frontend must unlock using the configured normal unlock method before accepting.
- there is no special "stronger password just for Accept/Open" rule.
- `Open` is frontend navigation after successful normal unlock; it is not a special Core acceptance mode.
- accepting a new Live request while locked does NOT automatically make it the locked foreground/PTT target.

#### Privacy

For a restricted client:

- `SHOW_ALL` may receive permitted identity metadata.
- `ANONYMIZE` must not expose peer identity/saved-vs-discovered status to the restricted client presentation path.
- `OFF` must expose no unsolicited call/notification presentation metadata to that restricted client.

Do not put message content in any locked notification/event projection.

---

## WP5 - Profile switching, graceful exit, shutdown, and purge

### WP5.1 Do not overload `SwitchCommand`

Existing `SwitchCommand` is peer/chat focus switching.

Do not reuse it for profile switching.

There is currently no running profile-switch command.

---

### WP5.2 Add frontend-neutral profile runtime switching orchestration

Because `ProfileManager` is profile-specific, implement profile switching at the appropriate frontend-neutral lifecycle/client/application layer rather than pretending a peer-focus command is a profile switch.

Required logical flow:

```text
current profile A
    -> inspect current canonical Live/pending state
    -> frontend may warn user if relevant state exists
    -> finalize any frontend-owned active Voice capture before switch
    -> apply normal fallback policy
    -> terminate active Live sessions for profile A
    -> if fallback OFF, preserve pending LIVE durably
    -> securely release/hard-lock profile A runtime
    -> discard profile-A volatile frontend state
    -> select/start/attach profile B
    -> require profile-B password
    -> obtain a fresh authoritative snapshot
```

Core/client must provide enough typed lifecycle results to make the sequence deterministic.

Important:

- profile switch must never silently discard pending Live data,
- profile switch must never automatically reconnect pending Live state when the user later returns,
- returning to profile A shows disconnected/pending state and requires explicit `Reconnect` or fallback,
- no profile A notifications/transient state bleed into profile B,
- do not implement legacy DB migration work.

Terminal may continue selecting a profile before launch and is not required to expose runtime profile switching. Shared lifecycle helpers may be used by Terminal only if they do not alter its behavior.

---

### WP5.3 Normal graceful profile exit / shutdown preparation

Provide or consolidate a reusable Core lifecycle operation for normal profile exit used by:

- profile switch,
- Embedded normal power-off.

Required normal exit behavior:

1. active Voice capture is finalized by the frontend before invoking the Core exit phase,
2. apply the normal fallback policy to eligible pending LIVE data,
3. do not wait for remote DROP delivery,
4. it is sufficient for fallback/DROP state to be durably committed locally,
5. terminate active Live connections,
6. securely release/hard-lock the runtime,
7. return/emit deterministic completion.

If fallback is OFF:

- pending LIVE remains durable and recoverable for a later explicit user decision.

Normal shutdown is a reliability-preserving path.

---

### WP5.4 Purge/self-destruct is NOT graceful shutdown

Purge is the opposite priority.

Once self-destruct is accepted:

- do not finalize PTT/Voice for delivery,
- do not fallback,
- do not reconnect,
- do not flush pending messages to peers,
- do not emit new normal user notifications,
- abort/stop reliability work,
- enter destruction immediately,
- destroy key access first,
- then perform best-effort filesystem cleanup,
- then allow device shutdown.

Purge MUST preempt normal reliability policy.

Ensure background reconnect/fallback workers cannot race after destruction begins.

The existing `daemon.self_destruct_requires_unlock` security setting must remain meaningful. Do not weaken it globally merely for future hardware purge. If the Embedded deployment later disables it, Core must still rely on restricted/trusted local IPC controls as documented.

### WP5.5 Observable destruction completion

`SelfDestructInitiatedEvent` exists, but the future device shutdown flow needs an unambiguous signal that irreversible destruction has progressed far enough to allow hardware shutdown.

Provide one robust frontend-neutral completion mechanism, preferably a typed event such as:

```text
SelfDestructCompletedEvent
```

or an equivalently deterministic documented daemon-exit contract.

Do not treat `SelfDestructInitiatedEvent` as permission to cut power immediately before key destruction has occurred.

Terminal may ignore the completion event if it does not need it.

---

## WP6 - Preserve proven contact, identity, history, and transport behavior

These areas are already aligned with the target design. Do not unnecessarily rewrite them.

### Contacts

Preserve:

- saved vs discovered peer distinction,
- `AddContactCommand` promotion behavior,
- rename changes alias while Onion identity remains stable,
- remove may hard-delete only when safe,
- otherwise remove/demotion anonymizes the peer and preserves required references,
- active/referenced discovered peers remain until safe orphan cleanup,
- `ClearContactsCommand` uses the same downgrade/anonymize rules.

Do not add pinning to Core. Pinning is frontend-local and keyed by stable Onion identity.

### Address / QR

Preserve:

- current address retrieval,
- address generation restrictions,
- QR validation foundation.

"My QR" and QR user flow are Embedded UI work, not this task.

### Retunnel

Preserve:

- existing retunnel command,
- initiated/success/failure typed events,
- recovery semantics.

User-facing wording such as "Change route" belongs to the later UI.

### History

Preserve:

- projected user-facing history,
- raw transport history,
- `record_live_history`,
- `record_drop_history`,
- `ephemeral_messages`.

Do not create a notification/history side store.

---

## WP7 - Terminal integration and regression requirements

The Terminal is a consumer of the same Core contract.

### 7.1 Existing Terminal workflows that must remain operational

At minimum:

- bootstrap/init/auth,
- active profile password/session auth,
- startup state,
- `/connect`,
- `/accept`,
- `/reject`,
- `/disconnect`,
- `/switch`,
- `/fallback`,
- `/retunnel`,
- `/inbox`,
- `/sessions`,
- `/transport`,
- `/contacts list/add/remove/rename`,
- LIVE text send,
- DROP text send,
- pending text during genuine reconnect,
- reconnect/replay,
- settings/config CLI,
- profile management CLI.

### 7.2 Required Terminal adaptations

#### Selective fallback

No UX change required. `/fallback <peer>` remains bulk fallback.

#### MarkRead filter

Terminal can continue omitting the filter to preserve its mixed chat semantics.

#### Read receipts

Terminal keeps handling `ReadReceiptEvent`, but default Core setting means none are sent locally unless enabled.

#### Corrected disconnect actor/reason

Update Terminal tests/handling for system safety disconnects so they are not treated as local-user disconnects.

Do not preserve a wrong actor merely to keep an old rendering path.

#### Voice / non-text content

Terminal must not crash.

Replace blind `event.content.text` assumptions with typed content dispatch.

A Voice/unsupported placeholder is sufficient for this refactor.

Terminal is not required to capture/play Voice.

#### New optional fields/events

Terminal must safely ignore additive state revision fields and events it does not need.

### 7.3 Terminal transient state

Do not move Terminal-only presentation state into Core merely because the Embedded UI will use different presentation.

Examples that may remain frontend-local:

- Terminal focus,
- transient rendered scrollback,
- prompt state,
- buffered UI notification timing,
- Terminal transport presentation state where it is only presentation.

If a state is actually required for correctness across UIs/restarts, move the canonical fact into Core and let Terminal derive its presentation from it.

---

## WP8 - Settings additions and defaults

Add/update the canonical settings registry and generated docs.

Required additions:

### `daemon.send_read_receipts`

```text
type: bool
default: false
profile override: yes
```

### pending LIVE resource limits

Add finite count and byte limits, profile-aware.

Names should follow existing convention, e.g.:

```text
daemon.max_pending_live_msgs
daemon.max_pending_live_bytes
```

### Voice buffer budget

Add a finite local retained Voice budget, e.g.:

```text
daemon.max_live_voice_buffer_bytes
```

The exact naming may be adjusted to fit the settings registry, but there must be one clear canonical resource budget.

Do **not** add:

- a user-configurable Voice segment duration,
- TTL-based auto-deletion of pending LIVE content.

Device UI presentation preferences such as:

- auto-play default,
- lock-screen display wording,
- pinning,
- notification-center size/presentation,

do not belong in daemon settings unless needed for Core security enforcement.

PIN verifier/security metadata is auth state, not a plain-text generic setting.

---

## WP9 - Security requirements

The refactor must preserve/improve the following.

### Input and resource validation

- bound all peer-controlled sizes before allocation,
- bound Voice chunk sizes,
- bound retained bytes,
- validate `msg_id`,
- validate selective fallback ownership/state,
- validate targeted delete ownership/state,
- prevent cross-peer ID substitution.

### No content in notification metadata

New structured notification/lifecycle events must not include arbitrary message body content.

### No secret logging

Do not log:

- profile passwords,
- PIN,
- PIN verifier material,
- PMK/key material,
- raw secret blobs.

### PIN

Use a salted memory-hard verifier/KDF suitable to the existing auth model. PIN is not a storage-encryption key.

### Purge

Purge must disable/race-proof normal reconnect/fallback activity before irreversible destruction.

### Privacy

`send_read_receipts=false` is the default.

History-disabled/ephemeral modes must not be defeated by new snapshot/notification structures.

---

# 10. Required scenario tests

The final implementation is not done until the following scenarios pass.

## Scenario A - Selective text fallback

1. Alice has three pending LIVE messages to Bob.
2. Select only message 2.
3. Fallback message 2.
4. Verify:
   - same `msg_id`,
   - message 2 becomes DROP,
   - messages 1 and 3 remain pending LIVE,
   - replay cannot resend message 2 as LIVE,
   - `FallbackSuccessEvent` contains exactly message 2.

## Scenario B - Bulk fallback remains compatible

Existing `/fallback bob` from Terminal converts all pending LIVE messages exactly as before.

## Scenario C - Disconnected LIVE send with fallback OFF

1. Bob has no active/recovering Live state.
2. `fallback_to_drop=false`.
3. Attempt `SendMessageCommand(LIVE, ...)`.
4. Verify:
   - typed rejection,
   - no new pending LIVE spool item.

## Scenario D - Genuine reconnect send

1. Live transport drops into real reconnect grace.
2. Send new LIVE text during recovery.
3. Verify:
   - pending LIVE accepted,
   - reconnect sends/replays it,
   - no duplicate logical message.

## Scenario E - Overflow implicit hangup

1. Bob reaches `max_unseen_live_msgs` for Alice.
2. Alice sends one additional LIVE message.
3. Verify:
   - Bob does not ACK/store it,
   - Bob terminates session,
   - Bob event is `SYSTEM` + backlog-limit reason,
   - Alice sees only normal remote end semantics,
   - Alice's unACKed item remains pending,
   - Alice's fallback setting controls local outcome.

## Scenario F - DROP-only clear

1. Peer has DROP history plus pending/unseen LIVE state.
2. Clear peer conversation.
3. Verify:
   - DROP conversation data cleared according to command semantics,
   - LIVE unseen/pending unchanged,
   - Live connection unchanged.

## Scenario G - Delivery-aware mark-read

1. Alice has unread DROP and unseen LIVE.
2. `MarkRead(delivery=LIVE)`.
3. Verify DROP remains unread.
4. `MarkRead(delivery=DROP)`.
5. Verify LIVE state is not consumed.

## Scenario H - Remote read receipts disabled

1. `send_read_receipts=false`.
2. Consume a message.
3. Verify:
   - local read state updates,
   - ephemeral shredding still works,
   - no READ peer frame is emitted.

## Scenario I - Single DROP delete

Verify local-only deletion, dedupe preservation, no remote delete control message, and no accidental pending-send cancellation.

## Scenario J - Dismiss disconnected Live

1. Live disconnected.
2. Inbound unseen Live exists.
3. No outbound pending Live.
4. Dismiss.
5. Verify Core ephemeral state removed.
6. Repeat with outbound pending Live and verify typed rejection.

## Scenario K - Snapshot race

Create state changes while a frontend subscribes and retrieves startup state. Verify no missed or double-applied state using the revision mechanism.

## Scenario L - Voice streaming and full duplex

While Alice sends Voice to Bob:

- Bob sends Text to Alice,
- Bob sends Voice to Alice,
- both directions continue correctly,
- no Core half-duplex restriction.

## Scenario M - Voice reconnect resume

1. Alice starts one Voice turn.
2. Bob has played/ACKed chunks through offset N.
3. Transport drops.
4. Alice continues recording.
5. Reconnect.
6. Verify transfer/playback resumes after N, not from zero.
7. Final message has one `msg_id`.

## Scenario N - Voice fallback

1. Voice is partially delivered LIVE.
2. Recovery fails.
3. Auto fallback ON.
4. Finish/finalize Voice.
5. Verify complete Voice becomes DROP with same `msg_id`.
6. No duplicate LIVE replay remains.

## Scenario O - Voice buffer pressure

1. Reach 90% local Voice retention budget.
2. Verify typed warning.
3. Reach hard limit while recording.
4. Verify current Voice turn finalizes.
5. Verify new Voice cannot start until capacity exists and the physical/UI layer re-arms.
6. Fallback one pending Voice to DROP.
7. Verify LIVE capacity is released immediately after safe promotion.

## Scenario P - Restricted client lock

1. Terminal client authenticated.
2. Embedded-style client authenticated.
3. Restrict only Embedded-style client.
4. Verify Terminal remains unaffected.
5. Verify restricted client cannot query history/contacts/settings or send arbitrarily.
6. Verify permitted locked call actions obey policy.

## Scenario Q - PIN escalation

1. Configure PIN.
2. Restrict client.
3. Enter wrong PIN three times.
4. Verify PIN disabled for that unlock.
5. Verify profile password unlock succeeds.
6. Verify PIN works again after the next normal lock cycle.
7. Verify PIN never unlocks a cold/hard-locked encrypted profile.

## Scenario R - Profile switch with pending Live

1. Profile A has active Live + pending Live.
2. Auto fallback OFF.
3. Switch to profile B through the lifecycle coordinator.
4. Verify A's active connections terminate.
5. Verify A's pending Live remains durable.
6. Return to A later.
7. Verify no automatic reconnect/fallback; state appears disconnected/pending.

Repeat with fallback ON and verify safe local promotion to DROP before A is released.

## Scenario S - Normal power-off preparation

Verify normal shutdown waits only for safe local state transition/persistence, never for remote DROP delivery.

## Scenario T - Purge precedence

While:

- PTT/Voice active,
- reconnect running,
- pending LIVE exists,

trigger self-destruct.

Verify:

- no Voice finalization for delivery,
- no fallback,
- no reconnect,
- destruction starts immediately,
- key access destroyed before shutdown-completion signal,
- normal notification work does not resume,
- cleanup is best-effort after irreversible key destruction.

---

# 11. Documentation requirements

After implementation:

1. Regenerate `docs/generated/API.md`.
2. Regenerate `docs/generated/SETTINGS.md`.
3. Update `docs/contracts/EMBEDDED_UI.md` so its Core boundary matches the new canonical contracts.
4. Update glossary/architecture docs if new Voice or auth concepts introduce canonical terminology.
5. Remove stale TODOs that this refactor completes.
6. Do not manually edit generated docs.
7. Document new security-sensitive settings with explicit security notes.
8. Document that remote read receipts default to OFF.
9. Document purge vs graceful shutdown as different lifecycles.
10. Document that `LockCommand` remains a hard profile-runtime lock.

---

# 12. Explicit non-goals for Agent 1

Do NOT implement:

- Embedded screen layouts,
- HTML prototypes,
- touch navigation,
- software keyboard visuals,
- DROP/LIVE tabs,
- notification center UI,
- lock-screen UI,
- QR camera UI,
- playback UI,
- waveform UI,
- LED GPIO driver,
- display driver,
- speaker/microphone driver,
- acoustic echo cancellation implementation,
- message pinning,
- UI drafts,
- reply/quote,
- message previews in notifications,
- Voice segment-duration setting,
- automatic reconnect caused merely by opening/navigating to a peer.

Do not add speculative product features beyond this document.

---

# 13. Implementation style requirements

- Prefer typed commands/events over booleans and string parsing.
- Prefer explicit enums for reasons/policies.
- Keep human-readable strings in frontends/translators, not Core.
- Keep Onion identity as the stable peer identity across rename/demotion.
- Reuse existing message repository/spool semantics instead of building a second message database.
- Reuse the existing auth challenge/proof architecture where practical.
- Keep new events additive where that preserves Terminal compatibility.
- Remove obsolete unreleased code rather than carrying compatibility shims.
- Keep functions/modules cohesive; do not create an Embedded-specific god object in Core.
- Update tests together with behavior, not after.
- Treat security-sensitive edge cases as first-class acceptance criteria.

---

# 14. Definition of done

Agent 1 is complete only when all of the following are true:

- All required Work Packages above are implemented or explicitly proven unnecessary by current code.
- No required behavior is implemented only in Terminal.
- No Embedded UI has been built.
- Current Terminal workflows pass regression tests.
- Terminal does not crash on new typed content/events.
- Selective fallback works and preserves `msg_id`.
- Disconnected non-recovering LIVE cannot accumulate new pending messages merely because fallback is disabled.
- `ClearMessagesCommand` is DROP-only.
- Single local DROP deletion exists.
- `MarkReadCommand` can separate DROP and LIVE.
- remote read receipts default to OFF.
- system overflow disconnect has correct actor/reason.
- disconnected Live state can be safely dismissed without deleting outbound pending content.
- an authoritative race-safe aggregate startup snapshot exists.
- Voice is a first-class typed content path with bounded, resumable, fallback-capable LIVE behavior.
- full-duplex Text/Voice semantics are supported in Core.
- Voice resources are bounded without silent data deletion.
- restricted client/session lock exists without changing `LockCommand` semantics.
- optional Core PIN/quick-unlock exists with 3-attempt password escalation.
- profile switching has a frontend-neutral safe lifecycle.
- graceful profile exit/power-off preparation preserves reliability but does not wait for remote delivery.
- purge preempts reliability and has deterministic post-destruction completion semantics.
- privacy/history settings are not bypassed.
- generated API/settings docs match implementation.
- full tests, lint, formatting, and type checks pass.

At that point the Core/client/Terminal contract is ready for Agent 2 to implement `EMBEDDED_UI_SPEC.md`.
